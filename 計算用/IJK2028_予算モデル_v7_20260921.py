# -*- coding: utf-8 -*-
"""IJK 2028 予算モデル v7 / 2026-09-21（標準ライブラリのみ）。

実行: python IJK2028_予算モデル_v7_20260921.py --output-dir 任意の出力先
省略時は本ファイルと同じフォルダに計算結果 JSON を作成する。

最新方針:
* 24週表は宿泊・食事・通常プログラム込みの基本料金。
* 一般登録350人 = 全日150 + 前半100 + 後半100。36歳以上もこの内数。
* 一般36～40歳は1.5倍、41歳以上は2倍。協力者・大本/EPAは倍率なしの実費/無料。
* 年長一般参加者は原則ホテル、施設内個室は青年のみ。施設内年長者の約2割という
  目安は分母未定のため計算上限にしない。ホテル泊には同じ厳しい年齢上限なし。
* 全日7泊、短期3泊。ホテル代本人払い、施設内宿泊控除は仮に1泊1000円。
  控除は年齢・期間倍率を反映した参加費から引く。宿泊費の支出も同時に減らす。
* 食事は全日21食・短期11食を予算確保数として仮置き。実際の配食確定数ではない。
  ホテル客も原則全食を会場費用へ計上。ホテル朝食を理由とする自動控除はしない。
* 菜食補完/暑さ対策は短期4日/全日8日の0.5倍。記念品/保険/査証事務は一人分。
* 日帰りは第3・4・7日の有料各40人（仮）、無料延べ300人日（仮定）。
* 年齢未定の基準は全員基本倍率による収入比較。40人/80人の年長者例は需要予測ではない。
  基準の全日ホテル8人は定員不足の算術調整であり、実際のホテル需要予測ではない。
* 助成金/赤字補填は0。会場単価、個室有料20人、国別構成等はいずれも見積確定前。

"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable


VERSION = "v7_20260921"
TABLE = {
    "A": [265,275,280,290,300,305,315,325,335,340,350,360,365,375,385,390,400,410,420,425,435,445,450,460],
    "B": [230,235,245,250,255,260,270,275,280,285,295,300,305,310,320,325,330,335,345,350,355,360,370,375],
    "C": [200,205,210,215,215,220,225,230,235,240,245,250,250,255,260,265,270,275,280,285,285,290,295,300],
    "Cx": [130,135,135,140,140,145,145,150,150,155,155,160,160,165,165,170,170,175,175,180,180,185,185,190],
}
MIX_JP = {"A": .45, "B": .35, "C": .12, "Cx": .08}
MIX_EA = {"A": .25, "B": .45, "C": .20, "Cx": .10}
AGE_FACTOR = {"base": 1., "36_40": 1.5, "41_plus": 2.}
PERIOD_FACTOR = {"full": 1., "first": .7, "second": .7}
NIGHTS = {"full": 7, "first": 3, "second": 3}
NIGHT_MASK = {"full": (1,1,1,1,1,1,1), "first": (1,1,1,0,0,0,0), "second": (0,0,0,0,1,1,1)}


@dataclass(frozen=True)
class Cohort:
    """一般参加者のみ。協力者は別枠。base は35歳以下または年齢未定比較用。"""
    period: str
    age: str
    lodging: str
    count: int


def make_cohorts(full=150, first=100, second=100, *, older_full_each=0,
                 older_first_each=0, older_second_each=0) -> list[Cohort]:
    """each は36～40歳、41歳以上それぞれの人数。年長者は全員ホテルの仮例。"""
    result = []
    for period, total, each in (("full", full, older_full_each),
                                ("first", first, older_first_each),
                                ("second", second, older_second_each)):
        if each < 0 or total < each * 2:
            raise ValueError("年長参加者を含む一般参加総数の内訳にしてください")
        result.append(Cohort(period, "base", "onsite", total - each * 2))
        result.extend(Cohort(period, age, "hotel", each) for age in ("36_40", "41_plus"))
    return [c for c in result if c.count]


def average_fee(mix=None, distribution=(.5, .3, .2)):
    """申込週1～8/9～16/17～24の比率。各期間内は均等。"""
    mix = MIX_JP if mix is None else mix
    if set(mix) != set(TABLE) or abs(sum(mix.values()) - 1) > 1e-9:
        raise ValueError("国区分構成は A/B/C/Cx の合計1で指定してください")
    if len(distribution) != 3 or abs(sum(distribution) - 1) > 1e-9:
        raise ValueError("登録時期の構成は3期間の合計1で指定してください")
    if min(mix.values()) < 0 or min(distribution) < 0:
        raise ValueError("構成比を負にはできません")
    by_country = {g: sum(distribution[i] * sum(v[i*8:i*8+8])/8 for i in range(3))
                  for g, v in TABLE.items()}
    return sum(mix[g] * by_country[g] for g in mix), by_country


def nightly_occupancy(cohorts, staff_full=15):
    return [staff_full + sum(c.count * NIGHT_MASK[c.period][night]
                            for c in cohorts if c.lodging == "onsite") for night in range(7)]


def route_capacity_overflow(cohorts, capacity, staff_full):
    """比較用に不足床数だけ全日基本倍率群をホテルへ移す。需要予測には使わない。"""
    cohorts = list(cohorts)
    needed = max(0, max(nightly_occupancy(cohorts, staff_full)) - capacity)
    remaining = needed
    result = []
    for c in cohorts:
        if c.period == "full" and c.age == "base" and c.lodging == "onsite":
            moved = min(remaining, c.count)
            remaining -= moved
            if c.count > moved:
                result.append(replace(c, count=c.count-moved))
            if moved:
                result.append(replace(c, lodging="hotel", count=moved))
        else:
            result.append(c)
    if remaining:
        raise ValueError("定員超過。短期や年長者を含む宿泊配置を明示してください")
    return result, needed


def unit_cost(period, lodging, *, lodging_night=1000, meal_price=450,
              full_meals=21, short_meals=11):
    """宿泊は実際の泊数、食事は予算確保数、一人ごとの費用は期間にかかわらず一人分。"""
    day_ratio = 1 if period == "full" else .5
    return {
        "lodging": NIGHTS[period]*lodging_night if lodging == "onsite" else 0,
        "meals": (full_meals if period == "full" else short_meals)*meal_price,
        "vegetarian": 1600*day_ratio, "heat": 1000*day_ratio,
        "kit": 700, "insurance": 800, "visa_admin": 300,
    }


def scenario(label="年齢未定・基本倍率の比較基準", *, cohorts: Iterable[Cohort] | None=None,
             full=150, first=100, second=100, staff_full=15, capacity=257,
             private_youth_full=20, mix=None, fx=170, distribution=(.5,.3,.2),
             nonmember_share=0., nonmember_full_euro=50, nonmember_short_euro=50,
             paid_days=3, paid_per_day=40, older_day_share=.5, free_day_person_days=300,
             day_cost=800, lodging_night=1000, meal_price=450, full_meals=21, short_meals=11,
             hotel_refund_night=1000, fixed=4_500_000, tejo=2_000_000, excursion=400_000,
             fee_rate=.038, reserve_rate=.12, helper_recovery_yen=0,
             grants=0, deficit_support=0, auto_hotel_overflow=True):
    """helpers の回収収入は実費/無料を直接円指定し、年齢倍率は決して掛けない。

    非会員は既定0のため短期加算50/35ユーロの未決が基準収支へ影響しない。
    0以外で使う際は nonmember_short_euro を方針確定後に明示する。
    外部ホテル代と遠足事業費は本人払いの別会計。本体には遠足支援枠だけを計上。
    """
    mix = dict(MIX_JP if mix is None else mix)
    cohorts = list(make_cohorts(full, first, second) if cohorts is None else cohorts)
    for c in cohorts:
        if c.period not in NIGHTS or c.age not in AGE_FACTOR or c.lodging not in ("onsite", "hotel"):
            raise ValueError(f"不正な参加区分: {c}")
        if not isinstance(c.count, int) or c.count < 0:
            raise ValueError("人数は0以上の整数")
    if not 0 <= nonmember_share <= 1 or not 0 <= older_day_share <= 1:
        raise ValueError("構成比は0～1")
    if paid_days not in (0,1,2,3):
        raise ValueError("有料日帰り受付は現日程の最大3日")
    if min(staff_full, private_youth_full, paid_per_day, free_day_person_days, helper_recovery_yen,
           grants, deficit_support, lodging_night, meal_price, hotel_refund_night) < 0:
        raise ValueError("人数・費用・収入を負にはできません")
    initial_registration = sum(c.count for c in cohorts)
    if auto_hotel_overflow:
        cohorts, routed = route_capacity_overflow(cohorts, capacity, staff_full)
    else:
        routed = 0
    occupancy = nightly_occupancy(cohorts, staff_full)
    if max(occupancy) > capacity:
        raise ValueError("施設内宿泊が作業仮定の定員を超えています")
    youth_full_onsite = sum(c.count for c in cohorts
                            if c.period == "full" and c.age == "base" and c.lodging == "onsite")
    if private_youth_full > youth_full_onsite:
        raise ValueError("個室加算は施設内全日の青年一般参加者数以下にしてください")
    avg_euro, by_country = average_fee(mix, distribution)
    avg_yen = avg_euro*fx
    registration = sum(c.count for c in cohorts)
    assert registration == initial_registration  # ホテル移動や年齢倍率で人数を増やさない。
    counts = {p: sum(c.count for c in cohorts if c.period == p) for p in NIGHTS}
    ages = {age: sum(c.count for c in cohorts if c.age == age) for age in AGE_FACTOR}
    income = {
        "full_basic": counts["full"]*avg_yen,
        "first_basic": counts["first"]*.7*avg_yen,
        "second_basic": counts["second"]*.7*avg_yen,
        "age_uplift": sum(c.count*avg_yen*PERIOD_FACTOR[c.period]*(AGE_FACTOR[c.age]-1) for c in cohorts),
        "private_youth": private_youth_full*.5*avg_yen,
        "nonmember": sum(c.count*nonmember_share*fx*(nonmember_full_euro if c.period == "full"
                                                   else nonmember_short_euro) for c in cohorts),
        "paid_day": paid_days*paid_per_day*(4000+3000*older_day_share),
        "hotel_lodging_credit": -sum(c.count*NIGHTS[c.period]*hotel_refund_night
                                     for c in cohorts if c.lodging == "hotel"),
        "helpers_actual_cost_recovery": helper_recovery_yen,
        "grants": grants,
        "deficit_support": deficit_support,
    }
    revenue = sum(income.values())
    cost_kwargs = dict(lodging_night=lodging_night, meal_price=meal_price, full_meals=full_meals,
                       short_meals=short_meals)
    components = {k: 0. for k in unit_cost("full", "onsite", **cost_kwargs)}
    cohort_details = []
    for c in cohorts:
        unit = unit_cost(c.period, c.lodging, **cost_kwargs)
        for k in components:
            components[k] += c.count*unit[k]
        row = asdict(c)
        row.update(unit_expenses_yen=unit, variable_expenses_yen=c.count*sum(unit.values()))
        cohort_details.append(row)
    staff_unit = unit_cost("full", "onsite", **cost_kwargs)
    for k in components:
        components[k] += staff_full*staff_unit[k]
    # 助成金・赤字補填には参加費の決済手数料を掛けない。基準はいずれも0。
    fee_base = revenue - grants - deficit_support
    expenses = {
        "ordinary_and_staff_variable": sum(components.values()),
        "day_reception": (paid_days*paid_per_day+free_day_person_days)*day_cost,
        "fixed_common": fixed, "tejo_support": tejo, "excursion_support": excursion,
        "payment_fees": fee_base*fee_rate,
    }
    subtotal = sum(expenses.values())
    expenses["reserve"] = subtotal*reserve_rate
    cost = sum(expenses.values())
    hotel_counts = {p: sum(c.count for c in cohorts if c.period == p and c.lodging == "hotel") for p in NIGHTS}
    gross_occupancy = [staff_full + sum(c.count*NIGHT_MASK[c.period][n] for c in cohorts) for n in range(7)]
    return {
        "label": label, "version": VERSION,
        "ordinary_registration": registration, "ordinary_period_counts": counts,
        "ordinary_age_counts": ages, "free_or_actual_cost_staff": staff_full,
        "age_composition_is_forecast": False,
        "capacity_routed_hotel_full": routed,
        "hotel_registration": sum(hotel_counts.values()), "hotel_period_counts": hotel_counts,
        "nightly_attendance_including_hotel_and_staff": gross_occupancy,
        "nightly_onsite_including_staff": occupancy,
        "nightly_hotel": [g-o for g,o in zip(gross_occupancy, occupancy)],
        "onsite_bed_nights": sum(occupancy),
        "meal_allowance_total": (counts["full"]+staff_full)*full_meals+(counts["first"]+counts["second"])*short_meals,
        "quantity_notice": "泊数は実滞在、食数は予算仮定。",
        "paid_day_person_days": paid_days*paid_per_day,
        "free_day_person_days": free_day_person_days,
        "average_basic_fee_euro": avg_euro, "average_basic_fee_yen": avg_yen,
        "average_by_country_euro": by_country,
        "income_yen": income, "variable_expense_components_yen": components,
        "expenses_yen": expenses, "expense_subtotal_before_reserve_yen": subtotal,
        "revenue_yen": revenue, "expenses_total_yen": cost, "balance_yen": revenue-cost,
        # 予算説明資料の集計に使う円単位の要約値。
        "revenue": revenue, "cost": cost, "balance": revenue-cost, "occupancy": occupancy,
        "cohorts": cohort_details, "staff_unit_expenses_yen": staff_unit,
        "assumptions": {
            "fx": fx, "country_mix": mix, "registration_distribution": distribution,
            "capacity": capacity, "private_youth_full": private_youth_full,
            "lodging_night_yen": lodging_night, "hotel_credit_night_yen": hotel_refund_night,
            "meal_price_yen": meal_price, "full_meal_allowance": full_meals,
            "short_meal_allowance": short_meals, "meal_counts_are_confirmed": False,
            "short_vegetarian_heat_fraction": .5, "nonmember_share": nonmember_share,
            "nonmember_full_euro": nonmember_full_euro, "nonmember_short_euro": nonmember_short_euro,
            "day_older_share": older_day_share, "payment_rate": fee_rate, "reserve_rate": reserve_rate,
            "site_older_cap": "施設内の36歳以上一般参加者に約2割の目安。分母未定のため人数上限へ変換しない",
            "hotel_older_cap": "施設内と同じ厳しい年齢人数上限なし",
            "hotel_breakfast_automatic_deduction": False,
        },
    }


def hotel_fee_example(age, period, base_euro=300, fx=170, refund_night=1000):
    return base_euro*fx*AGE_FACTOR[age]*PERIOD_FACTOR[period]-NIGHTS[period]*refund_night


def build_report():
    base = scenario()
    age40 = scenario("仮例：350人のうち年長40人がホテル泊（需要予測ではない）",
                     cohorts=make_cohorts(older_full_each=10, older_first_each=5, older_second_each=5))
    age80 = scenario("仮例：350人のうち年長80人がホテル泊（需要予測ではない）",
                     cohorts=make_cohorts(older_full_each=20, older_first_each=10, older_second_each=10))
    rows = [base, age40, age80]
    for n in (0,10,20):
        rows.append(scenario(f"青年の有料個室{n}人", private_youth_full=n))
    for price in (450,550,650):
        rows.append(scenario(f"食事1食{price}円", meal_price=price))
    rows.append(scenario("短期食事10食の感度（配食確定前）", short_meals=10))
    for days in (1,2,3):
        rows.append(scenario(f"有料日帰り受付{days}日", paid_days=days))
    rows.append(scenario("施設単価だけ上振れ：宿泊1800円・食事1日1900円相当", lodging_night=1800, meal_price=1900/3))
    rows.append(scenario("施設単価と共通費が上振れ：宿泊1800円・食事1日1900円相当・共通費25%増", lodging_night=1800, meal_price=1900/3, fixed=4_500_000*1.25))
    rows.append(scenario("国別構成EA仮定", mix=MIX_EA))
    rows.append(scenario("全日125人・前後半各100人", full=125))
    rows.append(scenario("全日150人・前後半各90人", first=90, second=90))
    rows.append(scenario("全日150人・前後半各75人", first=75, second=75))
    for fx in (160,179):
        rows.append(scenario(f"円換算1ユーロ{fx}円", fx=fx))
    examples = {f"{age}_{p}": hotel_fee_example(age, p)
                for age in ("36_40", "41_plus") for p in ("full", "first")}
    assert examples == {"36_40_full": 69500, "36_40_first": 50550,
                        "41_plus_full": 95000, "41_plus_first": 68400}
    assert all(len(v) == 24 for v in TABLE.values())
    assert all(row["ordinary_registration"] == 350 for row in (base, age40, age80))
    assert base["nightly_attendance_including_hotel_and_staff"] == [265,265,265,165,265,265,265]
    assert base["nightly_onsite_including_staff"] == [257,257,257,157,257,257,257]
    assert age40["nightly_onsite_including_staff"] == [235,235,235,145,235,235,235]
    assert age80["nightly_onsite_including_staff"] == [205,205,205,125,205,205,205]
    assert all(max(row["nightly_onsite_including_staff"]) <= 257 for row in (base, age40, age80))
    assert abs(base["balance_yen"] - 643037.1104) < .01
    assert base["income_yen"]["paid_day"] == 660000
    # 同じ年齢・人数・定員で全日1人だけをホテルへ動かすと、宿泊支出と収入控除が同額動く。
    before = scenario("検証・全日100人", full=100)
    after_cohorts = [Cohort("full","base","onsite",99), Cohort("full","base","hotel",1),
                    Cohort("first","base","onsite",100), Cohort("second","base","onsite",100)]
    after = scenario("検証・1人ホテル", cohorts=after_cohorts)
    assert after["revenue_yen"] - before["revenue_yen"] == -7000
    assert after["variable_expense_components_yen"]["lodging"] - before["variable_expense_components_yen"]["lodging"] == -7000
    assert after["variable_expense_components_yen"]["meals"] == before["variable_expense_components_yen"]["meals"]
    # 個室人数は青年人数の範囲内だけ。年長者へ自動加算しない。
    invalid = [Cohort("full", "41_plus", "onsite", 20)]
    try:
        scenario(cohorts=invalid, private_youth_full=1)
    except ValueError:
        pass
    else:
        raise AssertionError("年長一般参加者の個室を受け付けてしまった")
    return {
        "version": VERSION,
        "notice": "需要予測ではなく現条件の比較計算。基準は年齢未定・全員基本倍率。年長40/80人例は任意の感度分析。",
        "price_table_euro": TABLE,
        "hotel_fee_examples_B_week12_yen": examples,
        "verification": "24週間料金表・年長者を内数とする登録総数・宿泊定員・基準収支・ホテル控除/費用同時減少・青年のみ個室を検証済み",
        "scenarios": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    report = build_report()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "IJK2028_予算モデル_v7_計算結果_20260921.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in report["scenarios"]:
        print(f"{row['label']}: 収入{row['revenue_yen']/10000:.2f}万円、支出{row['expenses_total_yen']/10000:.2f}万円、収支{row['balance_yen']/10000:+.2f}万円")
    print(f"検証完了: {json_path.name}")


if __name__ == "__main__":
    main()
