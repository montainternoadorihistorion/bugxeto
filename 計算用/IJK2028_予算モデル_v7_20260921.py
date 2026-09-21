# -*- coding: utf-8 -*-
"""IJK 2028 予算モデル v7 / 2026-09-21 年齢料金改定版（標準ライブラリのみ）。

実行: python IJK2028_予算モデル_v7_20260921.py --output-dir 任意の出力先
省略時は本ファイルと同じフォルダに計算結果 JSON を作成する。

最新方針:
* 表示基本料金Cは非会員・雑魚寝・食事付き・全日程・25～35歳。
  TABLEは従来の25～35歳会員相当額Bを保持し、C=B+50ユーロとする。
  年齢倍率はCへ掛ける。全日会員料金=C×年齢倍率-50、非会員料金=C×年齢倍率。
  短期は会員・非会員それぞれの全日料金×0.7。短期会員料金=(C×年齢倍率-50)×0.7、
  短期非会員料金=C×年齢倍率×0.7となり、会員差額は35ユーロ。
  主催側の料金方針は確定。TEJOの会員・patrono資格の適用条件は別途調整する。
  従来25参考ケースは非会員割合0のまま保持する。
  個室追加はBの50%を維持し、年齢割引・割増を掛けない。若年者の費用は減額しない。
* 一般登録350人 = 全日150 + 前半100 + 後半100。36歳以上もこの内数。
* 年齢倍率は16歳以下0.7、17～24歳0.8、25～35歳1、36歳以上一律1.5。
  協力者・大本/EPAは倍率なしの実費/無料。年齢は開催初日で判定する案。
* 年長一般参加者は原則ホテル、施設内個室は青年のみ。施設内年長者の約2割という
  目安は分母未定のため計算上限にしない。ホテル泊には同じ厳しい年齢上限なし。
* 全日7泊、短期3泊。ホテル代本人払い、施設内宿泊控除は仮に1泊1000円。
  控除は年齢・期間倍率を反映した参加費から引く。宿泊費の支出も同時に減らす。
* 食事は全日21食・短期11食を予算確保数として仮置き。実際の配食確定数ではない。
  ホテル客も原則全食を会場費用へ計上。ホテル朝食を理由とする自動控除はしない。
* 菜食補完/暑さ対策は短期4日/全日8日の0.5倍。記念品/保険/査証事務は一人分。
* 日帰りは第3・4・7日の有料各40人（仮）、無料延べ300人日（仮定）。
* 年齢未反映参考値は全員25～35歳・会員相当額による比較値で、若年割引も未反映。
  年長40/80人と若年を含む4ケースは感度分析であり、年齢構成の需要予測ではない。
  参考値の全日ホテル8人は定員不足の算術調整であり、実際のホテル需要予測ではない。
* 助成金/赤字補填は0。会場単価、個室有料20人、国別構成等はいずれも見積確定前。
* 基本の見通しは主催側の年齢比5:40:40:15を350人へ丸めて18/140/140/52人。
  各期への配分と36歳以上52人全員のホテル配置は計算上の仮置き。
  一般参加350人のTEJO会員を主催側の見込みどおり30%（105人）、非会員70%（245人）
  とする。各年齢・期間へ一律の割合を適用する点は仮定。日帰り・免除スタッフには適用しない。
  従来25ケースを比較用に維持し、基本と条件変更の8ケースを別配列へ保存する。

"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping


VERSION = "v7_20260921"
REVISION = "年齢料金改定版：16歳以下0.7、17～24歳0.8、25～35歳1、36歳以上1.5"
TABLE = {
    "A": [265,275,280,290,300,305,315,325,335,340,350,360,365,375,385,390,400,410,420,425,435,445,450,460],
    "B": [230,235,245,250,255,260,270,275,280,285,295,300,305,310,320,325,330,335,345,350,355,360,370,375],
    "C": [200,205,210,215,215,220,225,230,235,240,245,250,250,255,260,265,270,275,280,285,285,290,295,300],
    "Cx": [130,135,135,140,140,145,145,150,150,155,155,160,160,165,165,170,170,175,175,180,180,185,185,190],
}
MIX_JP = {"A": .45, "B": .35, "C": .12, "Cx": .08}
MIX_EA = {"A": .25, "B": .45, "C": .20, "Cx": .10}
BASE_AGE_KEY = "25_35"
AGE_FACTOR = {"16_or_under": .7, "17_24": .8, BASE_AGE_KEY: 1., "36_plus": 1.5}
YOUTH_AGE_KEYS = frozenset(("16_or_under", "17_24", BASE_AGE_KEY))
PERIOD_FACTOR = {"full": 1., "first": .7, "second": .7}
NIGHTS = {"full": 7, "first": 3, "second": 3}
NIGHT_MASK = {"full": (1,1,1,1,1,1,1), "first": (1,1,1,0,0,0,0), "second": (0,0,0,0,1,1,1)}


@dataclass(frozen=True)
class Cohort:
    """一般参加者のみ。協力者は別枠。年齢区分はAGE_FACTORの4区分。"""
    period: str
    age: str
    lodging: str
    count: int


def age_key_for_age(age_years):
    """開催初日時点の満年齢を料金区分へ対応させる。36歳以上はすべて同じ区分。"""
    if type(age_years) is not int or age_years < 0:
        raise ValueError("年齢は0以上の整数")
    if age_years <= 16:
        return "16_or_under"
    if age_years <= 24:
        return "17_24"
    if age_years <= 35:
        return BASE_AGE_KEY
    return "36_plus"


def make_cohorts(full=150, first=100, second=100, *,
                 age_counts: Mapping[str, Mapping[str, int]] | None=None) -> list[Cohort]:
    """各期の総数の内訳を指定する。未指定の残数は25～35歳、36歳以上はホテル。

    例: age_counts={"full": {"17_24": 40, "36_plus": 20},
                    "first": {"17_24": 30, "36_plus": 10},
                    "second": {"17_24": 30, "36_plus": 10}}
    25_35を明記する場合は各期の人数合計も一致させる。宿泊先の個別指定にはCohortを使う。
    """
    age_counts = {} if age_counts is None else age_counts
    if set(age_counts) - set(NIGHTS):
        raise ValueError("年齢内訳の期間はfull/first/secondで指定してください")
    result = []
    for period, total in (("full", full), ("first", first), ("second", second)):
        counts = dict(age_counts.get(period, {}))
        if set(counts) - set(AGE_FACTOR):
            raise ValueError("年齢内訳は16_or_under/17_24/25_35/36_plusで指定してください")
        if any(type(n) is not int or n < 0 for n in (total, *counts.values())):
            raise ValueError("人数は0以上の整数")
        if BASE_AGE_KEY not in counts:
            counts[BASE_AGE_KEY] = total - sum(counts.values())
        if min(counts.values()) < 0 or sum(counts.values()) != total:
            raise ValueError("各期の年齢内訳の合計を、一般参加総数と一致させてください")
        for age in AGE_FACTOR:
            count = counts.get(age, 0)
            if count:
                result.append(Cohort(period, age, "hotel" if age == "36_plus" else "onsite", count))
    return result


def participant_fee_euro(age, period="full", *, display_base_euro=350, member=True,
                         member_discount_full_euro=50, nonmember_short_euro=None):
    """年齢・会員区分を反映した全日料金に、参加期間の倍率を掛ける。

    短期の会員差額は全日差額×0.7に追従する。nonmember_short_euroの明示指定は
    過去の計算検証用であり、現在の料金方針では使わない。個室・ホテル控除・遠足は別。
    """
    if age not in AGE_FACTOR or period not in PERIOD_FACTOR:
        raise ValueError("年齢・参加期間が不正です")
    if min(display_base_euro, member_discount_full_euro) < 0 or (
            nonmember_short_euro is not None and nonmember_short_euro < 0):
        raise ValueError("料金・会員差額を負にはできません")
    # 通貨の例示で244.99999999999997等を出さず、未決定の価格丸めも加えない。
    full_member = (Decimal(str(display_base_euro))*Decimal(str(AGE_FACTOR[age]))
                   - Decimal(str(member_discount_full_euro)))
    if full_member < 0:
        raise ValueError("会員割引後の料金が負になる条件です")
    fee = full_member*Decimal(str(PERIOD_FACTOR[period]))
    if not member:
        difference = Decimal(str(member_discount_full_euro))*Decimal(str(PERIOD_FACTOR[period]))
        if period != "full" and nonmember_short_euro is not None:
            difference = Decimal(str(nonmember_short_euro))
        fee += difference
    return float(fee)


def average_fee(mix=None, distribution=(.5, .3, .2)):
    """25～35歳の全日会員相当額Bの平均。申込週3期間内は均等。"""
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
    """比較用に不足床数だけ全日25～35歳群をホテルへ移す。若年群を自動振替しない。"""
    cohorts = list(cohorts)
    needed = max(0, max(nightly_occupancy(cohorts, staff_full)) - capacity)
    remaining = needed
    result = []
    for c in cohorts:
        if c.period == "full" and c.age == BASE_AGE_KEY and c.lodging == "onsite":
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


def scenario(label="年齢未反映参考値：全員25～35歳・会員相当（需要予測ではない）", *,
             cohorts: Iterable[Cohort] | None=None,
             age_counts: Mapping[str, Mapping[str, int]] | None=None,
             full=150, first=100, second=100, staff_full=15, capacity=257,
             private_youth_full=20, mix=None, fx=170, distribution=(.5,.3,.2),
             nonmember_share=0., nonmember_full_euro=50, nonmember_short_euro=50,
             paid_days=3, paid_per_day=40, older_day_share=.5, free_day_person_days=300,
             day_cost=800, lodging_night=1000, meal_price=450, full_meals=21, short_meals=11,
             hotel_refund_night=1000, fixed=4_500_000, tejo=2_000_000, excursion=400_000,
             fee_rate=.038, reserve_rate=.12, helper_recovery_yen=0,
             grants=0, deficit_support=0, auto_hotel_overflow=True):
    """helpers の回収収入は実費/無料を直接円指定し、年齢倍率は決して掛けない。

    従来の参考ケースを保持するため非会員割合の既定値は0、短期差額の既定値は50。
    最新の基本の見通しでは build_planning_cases が割合0.7と確定した短期差額35を明示する。
    外部ホテル代と遠足事業費は本人払いの別会計。本体には遠足支援枠だけを計上。
    """
    mix = dict(MIX_JP if mix is None else mix)
    if cohorts is not None and age_counts is not None:
        raise ValueError("cohortsとage_countsは同時に指定できません")
    cohorts = list(make_cohorts(full, first, second, age_counts=age_counts) if cohorts is None else cohorts)
    for c in cohorts:
        if c.period not in NIGHTS or c.age not in AGE_FACTOR or c.lodging not in ("onsite", "hotel"):
            raise ValueError(f"不正な参加区分: {c}")
        if type(c.count) is not int or c.count < 0:
            raise ValueError("人数は0以上の整数")
    if not 0 <= nonmember_share <= 1 or not 0 <= older_day_share <= 1:
        raise ValueError("構成比は0～1")
    if paid_days not in (0,1,2,3):
        raise ValueError("有料日帰り受付は現日程の最大3日")
    if min(staff_full, private_youth_full, paid_per_day, free_day_person_days, helper_recovery_yen,
           grants, deficit_support, lodging_night, meal_price, hotel_refund_night,
           nonmember_full_euro, nonmember_short_euro) < 0:
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
                            if c.period == "full" and c.age in YOUTH_AGE_KEYS and c.lodging == "onsite")
    if private_youth_full > youth_full_onsite:
        raise ValueError("個室加算は施設内全日の青年一般参加者数以下にしてください")
    avg_euro, by_country = average_fee(mix, distribution)
    avg_yen = avg_euro*fx
    display_avg_euro = avg_euro + nonmember_full_euro
    display_avg_yen = display_avg_euro*fx
    age_adjustments = [c.count*display_avg_yen*PERIOD_FACTOR[c.period]*(AGE_FACTOR[c.age]-1)
                       for c in cohorts]
    registration = sum(c.count for c in cohorts)
    assert registration == initial_registration  # ホテル移動や年齢倍率で人数を増やさない。
    counts = {p: sum(c.count for c in cohorts if c.period == p) for p in NIGHTS}
    ages = {age: sum(c.count for c in cohorts if c.age == age) for age in AGE_FACTOR}
    income = {
        "full_basic": counts["full"]*avg_yen,
        "first_basic": counts["first"]*.7*avg_yen,
        "second_basic": counts["second"]*.7*avg_yen,
        "age_discount": sum(min(0., amount) for amount in age_adjustments),
        "age_surcharge": sum(max(0., amount) for amount in age_adjustments),
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
        row["average_member_participation_fee_yen_before_lodging_adjustments"] = participant_fee_euro(
            c.age, c.period, display_base_euro=display_avg_euro,
            member_discount_full_euro=nonmember_full_euro,
            nonmember_short_euro=nonmember_short_euro)*fx
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
        "label": label, "version": VERSION, "revision": REVISION,
        "base_age_key": BASE_AGE_KEY,
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
        "average_member_base_fee_euro": avg_euro, "average_member_base_fee_yen": avg_yen,
        "average_display_basic_fee_euro": display_avg_euro,
        "average_display_basic_fee_yen": display_avg_yen,
        "average_by_country_member_base_euro": by_country,
        "average_by_country_display_basic_euro": {g: v+nonmember_full_euro for g, v in by_country.items()},
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
            "age_factors": AGE_FACTOR,
            "age_factors_apply_to": "非会員・雑魚寝・食事付き・全日程・25～35歳の表示基本額C",
            "private_addition_basis": "25～35歳の全日会員料金Bの50%。若年割引・年長割増は掛けない",
            "young_participant_cost_discount": False,
            "site_older_cap": "施設内の36歳以上一般参加者に約2割の目安。分母未定のため人数上限へ変換しない",
            "hotel_older_cap": "施設内と同じ厳しい年齢人数上限なし",
            "hotel_breakfast_automatic_deduction": False,
        },
    }


def hotel_fee_example(age, period, *, display_base_euro=350, member=True, fx=170,
                      refund_night=1000, nonmember_short_euro=None):
    return participant_fee_euro(age, period, display_base_euro=display_base_euro, member=member,
                               nonmember_short_euro=nonmember_short_euro)*fx-NIGHTS[period]*refund_night


def build_planning_cases():
    """主催側の年齢・会員構成見込みに基づく基本と条件変更、計8ケース。

    350人への丸め・期間配分・36歳以上全員のホテル配置は仮定。既存の比較25ケースは変えない。
    TEJO会員30%を各年齢・期間に一律適用。短期は各会員区分の全日料金×0.7。
    """
    age_counts = {
        "full": {"16_or_under": 8, "17_24": 60, "25_35": 60, "36_plus": 22},
        "first": {"16_or_under": 5, "17_24": 40, "25_35": 40, "36_plus": 15},
        "second": {"16_or_under": 5, "17_24": 40, "25_35": 40, "36_plus": 15},
    }
    specs = [
        ("基本の見通し：年齢比5:40:40:15、TEJO会員30%・非会員70%", {}),
        ("有料個室0人", {"private_youth_full": 0}),
        ("平均食事550円", {"meal_price": 550}),
        ("複合：個室0人・食事550円・日帰り2日", {
            "private_youth_full": 0, "meal_price": 550, "paid_days": 2}),
        ("東アジア寄りの国構成を置く比較", {"mix": MIX_EA}),
        ("早期申込70％・中期20％・後期10％を置く比較", {"distribution": (.7, .2, .1)}),
        ("無料運営25人", {"staff_full": 25}),
        ("施設単価上振れ：宿泊1800円・食事1日1900円相当・ホテル控除1800円", {
            "lodging_night": 1800, "meal_price": 1900/3, "hotel_refund_night": 1800}),
    ]
    rows = []
    for index, (label, changed) in enumerate(specs):
        parameters = {"nonmember_share": .7, "nonmember_short_euro": 35, **changed}
        row = scenario(label, age_counts=age_counts, **parameters)
        row["age_composition_is_forecast"] = True
        row["age_composition_basis"] = "主催側の年齢構成見込み。入金済み人数・実測値ではない"
        row["period_age_split_is_assumption"] = True
        row["planning_case_kind"] = "central_planning_case" if index == 0 else "sensitivity"
        row["changed_parameters_from_planning_case"] = changed
        row["comparison_notice"] = (
            "年齢比は主催側の見込み。各期への配分と36歳以上52人全員のホテル配置は仮置き。"
            "TEJO会員30%・非会員70%は主催側の見込みで、各年齢・期間への一律適用は仮定。"
            "短期は会員・非会員それぞれの全日料金の70%とする主催側方針を反映。"
            "条件変更は収支への影響を見る比較であり、その条件の需要予測・正式見積もりではない。")
        row["balance_before_reserve_yen"] = row["revenue_yen"]-row["expense_subtotal_before_reserve_yen"]
        row["reserve_yen"] = row["expenses_yen"]["reserve"]
        row["balance_after_reserve_yen"] = row["balance_yen"]
        row["member_fee_by_period_before_lodging_adjustments_yen"] = {
            period: sum(c["count"]*c["average_member_participation_fee_yen_before_lodging_adjustments"]
                        for c in row["cohorts"] if c["period"] == period)
            for period in NIGHTS}
        # 既存フィールドは「全員に会員料金を使った場合」の意味を維持する。
        # 実際の見通しには、一般参加者の会員・非会員構成を反映した別フィールドを使う。
        row["mixed_membership_fee_by_period_before_lodging_adjustments_yen"] = {
            period: row["member_fee_by_period_before_lodging_adjustments_yen"][period]
                    + row["ordinary_period_counts"][period]*row["assumptions"]["nonmember_share"]
                    * row["assumptions"]["fx"]
                    * row["assumptions"]["nonmember_full_euro" if period == "full" else "nonmember_short_euro"]
            for period in NIGHTS}
        row["period_fee_summary_notice"] = (
            "member_fee_by_periodは一般参加者全員に会員料金を適用した比較額。"
            "mixed_membership_fee_by_periodは会員30%・非会員70%を反映した見通し。"
            "いずれもホテル宿泊差引き・個室追加・日帰り収入を含まない。")
        rows.append(row)
    assumptions = {
        "age_order": ["16_or_under", "17_24", "25_35", "36_plus"],
        "user_ratio": {"16_or_under": 5, "17_24": 40, "25_35": 40, "36_plus": 15},
        "user_ratio_notice": "主催側が示した年齢構成の見込み5:40:40:15。確定登録人数ではない",
        "rounded_counts": {"16_or_under": 18, "17_24": 140, "25_35": 140, "36_plus": 52},
        "rounding_notice": "350人に換算した17.5/140/140/52.5人を、合計350人となる18/140/140/52人へ丸めた",
        "period_age_counts": age_counts,
        "period_split_assumption": "全日150人へ8/60/60/22、前半・後半各100人へ5/40/40/15と仮配分。年齢別の参加期間について主催側が別途予測した値ではない",
        "hotel_assignment_assumption": "36歳以上52人を全員ホテル泊に仮置き（全日22・前半15・後半15）。施設内の受入れ可能性を否定するものではない",
        "private_youth_full": 20,
        "membership_assumption": "主催側の見込みに基づき、一般参加350人のTEJO会員を30%・105人、非会員を70%・245人とする。確定登録人数ではない",
        "membership_scope": "全日150人・前半100人・後半100人の一般参加者350人。日帰り参加者と参加費免除の運営スタッフを含めない",
        "member_share": .3,
        "nonmember_share": .7,
        "membership_counts": {"member": 105, "nonmember": 245},
        "period_membership_counts": {
            "full": {"member": 45, "nonmember": 105},
            "first": {"member": 30, "nonmember": 70},
            "second": {"member": 30, "nonmember": 70}},
        "membership_distribution_assumption": "各年齢・参加期間・国区分・申込時期に会員30%・非会員70%を一律適用する仮定。年齢ごとの会員人数を整数で確定したものではない",
        "full_membership_difference_euro": 50,
        "short_membership_difference_euro": 35,
        "short_membership_difference_is_confirmed": True,
        "short_membership_difference_notice": "短期は会員・非会員それぞれの全日料金×0.7とする主催側方針が確定。全日差額50ユーロ×0.7で短期差額35ユーロ。TEJOの会員・patrono資格の適用条件は別途調整する",
        "common_average_assumption": "全期間・全年齢・個室利用者の国構成と申込時期を共通とする。実際の内訳が分かれば分けて更新する",
    }
    assert len(rows) == 8
    assert all(r["ordinary_registration"] == 350 for r in rows)
    assert all(r["ordinary_age_counts"] == assumptions["rounded_counts"] for r in rows)
    assert all(r["hotel_period_counts"] == {"full": 22, "first": 15, "second": 15} for r in rows)
    assert rows[0]["nightly_onsite_including_staff"] == [228, 228, 228, 143, 228, 228, 228]
    assert all(r["assumptions"]["nonmember_share"] == .7 for r in rows)
    assert all(r["assumptions"]["nonmember_short_euro"] == 35 for r in rows)
    assert all(r["income_yen"]["nonmember"] == 1_725_500 for r in rows)
    return assumptions, rows


def build_report():
    base = scenario()
    age40 = scenario("仮例：350人のうち年長40人がホテル泊（需要予測ではない）",
                     age_counts={"full": {"36_plus": 20}, "first": {"36_plus": 10},
                                 "second": {"36_plus": 10}})
    age80 = scenario("仮例：350人のうち年長80人がホテル泊（需要予測ではない）",
                     age_counts={"full": {"36_plus": 40}, "first": {"36_plus": 20},
                                 "second": {"36_plus": 20}})
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
    younger_specs = [
        ("感度①：17～24歳100人（40/30/30）、残り25～35歳（需要予測ではない）",
         {"full": {"17_24": 40}, "first": {"17_24": 30}, "second": {"17_24": 30}}),
        ("感度②：17～24歳100人と36歳以上40人（需要予測ではない）",
         {"full": {"17_24": 40, "36_plus": 20}, "first": {"17_24": 30, "36_plus": 10},
          "second": {"17_24": 30, "36_plus": 10}}),
        ("感度③：17～24歳150人（60/45/45）と36歳以上40人（需要予測ではない）",
         {"full": {"17_24": 60, "36_plus": 20}, "first": {"17_24": 45, "36_plus": 10},
          "second": {"17_24": 45, "36_plus": 10}}),
        ("感度④：②に16歳以下20人（10/5/5）を加え、25～35歳を減らす（需要予測ではない）",
         {"full": {"16_or_under": 10, "17_24": 40, "36_plus": 20},
          "first": {"16_or_under": 5, "17_24": 30, "36_plus": 10},
          "second": {"16_or_under": 5, "17_24": 30, "36_plus": 10}}),
    ]
    young_rows = [scenario(label, age_counts=counts) for label, counts in younger_specs]
    rows.extend(young_rows)
    full_fee_examples = {
        age: {"nonmember": participant_fee_euro(age, member=False),
              "member": participant_fee_euro(age)} for age in AGE_FACTOR
    }
    short_fee_examples = {
        age: {"nonmember": participant_fee_euro(age, "first", member=False),
              "member": participant_fee_euro(age, "first")} for age in AGE_FACTOR
    }
    examples = {f"36_plus_{label}_{membership}": hotel_fee_example("36_plus", period, member=member)
                for label, period in (("full", "full"), ("short", "first"))
                for membership, member in (("member", True), ("nonmember", False))}
    expected_full_fees = {
        "16_or_under": {"nonmember": 245., "member": 195.},
        "17_24": {"nonmember": 280., "member": 230.},
        "25_35": {"nonmember": 350., "member": 300.},
        "36_plus": {"nonmember": 525., "member": 475.},
    }
    assert full_fee_examples == expected_full_fees
    assert short_fee_examples == {
        "16_or_under": {"nonmember": 171.5, "member": 136.5},
        "17_24": {"nonmember": 196., "member": 161.},
        "25_35": {"nonmember": 245., "member": 210.},
        "36_plus": {"nonmember": 367.5, "member": 332.5},
    }
    # 全96基本料金・全4年齢区分・会員/非会員・前半/後半について70%を検証する。
    for member_bases in TABLE.values():
        for member_base in member_bases:
            display_base = member_base+50
            for age in AGE_FACTOR:
                for member in (True, False):
                    full_fee = Decimal(str(participant_fee_euro(
                        age, display_base_euro=display_base, member=member)))
                    for period in ("first", "second"):
                        short_fee = Decimal(str(participant_fee_euro(
                            age, period, display_base_euro=display_base, member=member)))
                        assert short_fee == full_fee*Decimal("0.7")
                for period, difference in (("full", 50), ("first", 35), ("second", 35)):
                    fees = [Decimal(str(participant_fee_euro(
                        age, period, display_base_euro=display_base, member=member)))
                            for member in (False, True)]
                    assert fees[0]-fees[1] == difference
    # 差額を変えた感度検証でも、短期の既定値は全日差額×0.7に追従する。
    assert participant_fee_euro("25_35", "first", member=False,
                               member_discount_full_euro=80) == 245.
    assert participant_fee_euro("25_35", "first", member=True,
                               member_discount_full_euro=80) == 189.
    assert examples == {"36_plus_full_member": 73750., "36_plus_full_nonmember": 82250.,
                        "36_plus_short_member": 53525., "36_plus_short_nonmember": 59475.}
    assert all(len(v) == 24 for v in TABLE.values())
    assert len(rows) == 25
    assert all(row["ordinary_registration"] == 350 for row in (base, age40, age80, *young_rows))
    assert all(row["ordinary_period_counts"] == {"full": 150, "first": 100, "second": 100}
               for row in young_rows)
    assert base["nightly_attendance_including_hotel_and_staff"] == [265,265,265,165,265,265,265]
    assert base["nightly_onsite_including_staff"] == [257,257,257,157,257,257,257]
    assert age40["nightly_onsite_including_staff"] == [235,235,235,145,235,235,235]
    assert age80["nightly_onsite_including_staff"] == [205,205,205,125,205,205,205]
    assert all(max(row["nightly_onsite_including_staff"]) <= 257 for row in (base, age40, age80, *young_rows))
    assert abs(base["balance_yen"] - 643037.1104) < .01
    assert base["income_yen"]["paid_day"] == 660000
    # 若年の料金割引だけでは、宿泊・食事等の数量や支出を減らさない。
    assert young_rows[0]["variable_expense_components_yen"] == base["variable_expense_components_yen"]
    assert all(row["variable_expense_components_yen"] == age40["variable_expense_components_yen"]
               for row in young_rows[1:])
    assert all(row["income_yen"]["private_youth"] == base["income_yen"]["private_youth"]
               for row in young_rows)
    # 同じ年齢・人数・定員で全日1人だけをホテルへ動かすと、宿泊支出と収入控除が同額動く。
    before = scenario("検証・全日100人", full=100)
    after_cohorts = [Cohort("full",BASE_AGE_KEY,"onsite",99), Cohort("full",BASE_AGE_KEY,"hotel",1),
                    Cohort("first",BASE_AGE_KEY,"onsite",100), Cohort("second",BASE_AGE_KEY,"onsite",100)]
    after = scenario("検証・1人ホテル", cohorts=after_cohorts)
    assert after["revenue_yen"] - before["revenue_yen"] == -7000
    assert after["variable_expense_components_yen"]["lodging"] - before["variable_expense_components_yen"]["lodging"] == -7000
    assert after["variable_expense_components_yen"]["meals"] == before["variable_expense_components_yen"]["meals"]
    # 個室人数は青年人数の範囲内だけ。年長者へ自動加算しない。
    invalid = [Cohort("full", "36_plus", "onsite", 20)]
    try:
        scenario(cohorts=invalid, private_youth_full=1)
    except ValueError:
        pass
    else:
        raise AssertionError("年長一般参加者の個室を受け付けてしまった")
    for age in YOUTH_AGE_KEYS:
        private = scenario(cohorts=[Cohort("full", age, "onsite", 20)], private_youth_full=20)
        assert private["income_yen"]["private_youth"] == base["income_yen"]["private_youth"]
    planning_assumptions, combined_rows = build_planning_cases()
    return {
        "version": VERSION, "revision": REVISION,
        "notice": "主催側の年齢構成見込み5:40:40:15とTEJO会員30%・非会員70%に基づく基本の見通しはplanning_caseが指すcombined_scenariosの先頭。短期は会員・非会員それぞれの全日料金の70%とする主催側方針が確定。会員割合の各年齢・期間への一律適用、期間配分・ホテル配置・提供単価等は仮定。scenariosの従来25ケースは需要予測ではなく比較用として維持。",
        "base_age_key": BASE_AGE_KEY,
        "age_factors": AGE_FACTOR,
        "price_table_euro": {g: [v+50 for v in values] for g, values in TABLE.items()},
        "price_table_basis": "非会員・雑魚寝・食事付き・全日程・25～35歳の表示基本料金C。年齢倍率はこの額へ掛ける。",
        "member_base_price_table_euro": TABLE,
        "member_base_price_table_basis": "25～35歳の全日会員料金B。表示基本料金CはB+50ユーロ。個室追加はBの50%。",
        "fee_formula": {
            "full_nonmember": "C×年齢倍率",
            "full_member": "C×年齢倍率-50ユーロ",
            "short_member": "(C×年齢倍率-50ユーロ)×0.7",
            "short_nonmember": "C×年齢倍率×0.7",
            "private_full": "(C-50ユーロ)×0.5を追加。35歳以下に同額で、年齢倍率は掛けない",
            "hotel": "年齢・会員・期間反映後の料金から会場内の未利用宿泊分を控除。ホテル代は本人別払い",
        },
        "membership_notice": "主催側方針は全日会員割引50ユーロ、短期は会員・非会員それぞれの全日料金×0.7（会員差額35ユーロ）で確定。TEJOの会員・patrono資格の適用条件は別途調整する。最新の見通しは一般参加350人の会員30%・非会員70%を反映。日帰り・免除スタッフに差額を加算しない。従来25参考ケースは非会員割合0のまま保持。",
        "full_fee_examples_B_week12_euro": full_fee_examples,
        "short_fee_examples_B_week12_euro": short_fee_examples,
        "hotel_fee_examples_B_week12_yen": examples,
        "verification": "24週間表示料金・4年齢区分の計算順・全96基本料金における会員/非会員の前半/後半料金=全日料金×0.7・会員差額全日50/短期35・若年/年長を内数とする350人・各期人数・定員・年齢未反映参考値・若年費用不変・ホテル控除/費用同時減少・35歳以下のみ個室を検証済み",
        "scenarios": rows,
        "planning_assumptions": planning_assumptions,
        "planning_case": {"collection": "combined_scenarios", "index": 0, "label": combined_rows[0]["label"]},
        "combined_scenarios": combined_rows,
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
    for row in report["combined_scenarios"]:
        print(f"{row['label']}: 予備費前{row['balance_before_reserve_yen']/10000:+.2f}万円、予備費{row['reserve_yen']/10000:.2f}万円、予備費後{row['balance_after_reserve_yen']/10000:+.2f}万円")
    print(f"検証完了: {json_path.name}")


if __name__ == "__main__":
    main()
