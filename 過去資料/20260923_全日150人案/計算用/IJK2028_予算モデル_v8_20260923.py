# -*- coding: utf-8 -*-
"""IJK 2028 予算モデル v8 / 2026-09-23 全日150人・8日間。

実行すると同じフォルダへ計算結果JSONを保存する。標準ライブラリのみ。
参加者150人に参加費免除の運営15人を別枠で仮置きする。短期料金は維持するが、
基本予算の前半・後半人数は0。150人へさらに短期200人を足さない。
会員30%、年齢5:40:40:15を8/60/60/22人へ丸め、36歳以上22人はホテルの仮配置。
料金の定義・96価格・年齢倍率・ホテル最低額/短期上限・個室条件はv7と同じ。
会場資料の227人は大部屋205人と小部屋22人を含む資料上の合計。確定利用定員ではない。
見学後の最新内訳は完全個室がLUMO館4室・別館15室程度。約19室として予算では19人分を置く。
有料個室19人は150人の内数。初期資料の小部屋8室を完全個室8室とは扱わない。
音響60万円・Wi-Fi10万円・暑さ対策約5万円は主催側が妥当とした予算目安で、見積・契約額ではない。
追加縮小案全体の共通費300万円・TEJO等100万円・遠足支援30万円は引き続き検討中。
旧350人の資料・モデルは過去資料へ保存し、ここでは旧料金の参考25ケースを出力しない。
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping


VERSION = "v8_20260923"
REVISION = "一般参加150人・全日7泊8日、運営15人別枠。完全個室はLUMO4室・別館15室程度、有料19人で計算。音響60万円・通信10万円・暑さ対策約5万円を主催側の予算目安として採用。縮小案全体は検討中。宿泊・施設合計100万円は条件付き比較。青年・TEJOによる会計管理"
DISPLAY_TABLE_OFFSET_EURO = 50  # TABLEの旧会員相当額Bから、確定済みの表示基本料金Cへの固定差額。
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


def require_number(name, value, *, minimum=0, maximum=None, strictly_positive=False):
    """条件変更時の誤入力を、収支へ紛れ込ませず明示して止める。丸めは行わない。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name}は数値で指定してください")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if not finite or value < minimum or (maximum is not None and value > maximum) or (
            strictly_positive and value <= 0):
        bounds = "0より大きい有限値" if strictly_positive else (
            f"{minimum}以上{maximum}以下の有限値" if maximum is not None else f"{minimum}以上の有限値")
        raise ValueError(f"{name}は{bounds}で指定してください")


def require_count(name, value):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}は0以上の整数で指定してください")


def require_flag(name, value):
    if type(value) is not bool:
        raise ValueError(f"{name}はTrue/Falseで指定してください")


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


def make_cohorts(full=150, first=0, second=0, *,
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
    require_flag("会員区分", member)
    require_number("表示基本料金", display_base_euro)
    require_number("全日会員割引", member_discount_full_euro)
    if nonmember_short_euro is not None:
        require_number("短期会員差額", nonmember_short_euro)
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


def private_addition_yen(age, period="full", *, actual_nights=None, addition_night=3000):
    """全日7泊の35歳以下一般参加者の施設内個室追加。他の料金倍率は掛けない。

    前半・後半の個室は提供しない。actual_nightsも7泊に限り、期間をfullと指定して
    短期個室の料金を計算することは認めない。
    """
    if age not in YOUTH_AGE_KEYS or period != "full":
        raise ValueError("施設内個室は全日7泊の35歳以下一般参加者専用。前半・後半参加では利用不可")
    nights = NIGHTS["full"] if actual_nights is None else actual_nights
    require_number("個室1泊追加額", addition_night)
    if type(nights) is not int or nights != NIGHTS["full"]:
        raise ValueError("個室は全日7泊のみ。1泊追加額は0以上")
    return nights*addition_night


def average_fee(mix=None, distribution=(.5, .3, .2)):
    """25～35歳の全日会員相当額Bの平均。申込週3期間内は均等。"""
    mix = MIX_JP if mix is None else mix
    if set(mix) != set(TABLE):
        raise ValueError("国区分構成は A/B/C/Cx の合計1で指定してください")
    for group, value in mix.items():
        require_number(f"国区分{group}の構成比", value, maximum=1)
    if len(distribution) != 3:
        raise ValueError("登録時期の構成は3期間の合計1で指定してください")
    for i, value in enumerate(distribution):
        require_number(f"登録時期{i+1}の構成比", value, maximum=1)
    if abs(sum(mix.values()) - 1) > 1e-9 or abs(sum(distribution) - 1) > 1e-9:
        raise ValueError("国区分構成・登録時期の構成はそれぞれ合計1で指定してください")
    by_country = {g: sum(distribution[i] * sum(v[i*8:i*8+8])/8 for i in range(3))
                  for g, v in TABLE.items()}
    return sum(mix[g] * by_country[g] for g in mix), by_country


def nightly_occupancy(cohorts, staff_full=15):
    require_count("運営人数", staff_full)
    return [staff_full + sum(c.count * NIGHT_MASK[c.period][night]
                            for c in cohorts if c.lodging == "onsite") for night in range(7)]


def route_capacity_overflow(cohorts, capacity, staff_full):
    """比較用に不足床数だけ全日25～35歳群をホテルへ移す。若年群を自動振替しない。"""
    cohorts = list(cohorts)
    require_count("施設内定員", capacity)
    require_count("運営人数", staff_full)
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
              full_meals=21, short_meals=11, heat_full_yen=300):
    """宿泊は実際の泊数、食事は予算確保数、一人ごとの費用は期間にかかわらず一人分。"""
    if period not in NIGHTS or lodging not in ("onsite", "hotel"):
        raise ValueError("参加期間・宿泊区分が不正です")
    require_number("施設宿泊1泊原価", lodging_night)
    require_number("食事1食原価", meal_price)
    require_number("全日暑さ対策費", heat_full_yen)
    require_count("全日食数", full_meals)
    require_count("短期食数", short_meals)
    day_ratio = 1 if period == "full" else .5
    return {
        "lodging": NIGHTS[period]*lodging_night if lodging == "onsite" else 0,
        "meals": (full_meals if period == "full" else short_meals)*meal_price,
        "vegetarian": 1600*day_ratio, "heat": heat_full_yen*day_ratio,
        "kit": 700, "insurance": 800, "visa_admin": 300,
    }


def average_hotel_fee_adjustment_yen(age, period, *, mix, distribution, fx,
                                         nonmember_share, member_discount_full_euro,
                                         nonmember_short_euro, refund_night,
                                         minimum_fee_yen, short_full_cap):
    """国・週・会員ごとにホテル最低額と短期上限を適用した調整額の加重平均。

    最低額・上限は非線形なので、全員の平均料金へ一度だけ適用すると誤差が出る。
    None/Falseは過去比較用に下限・上限を適用しない指定。施設内宿泊には呼び出さない。
    """
    if minimum_fee_yen is None and not short_full_cap:
        return 0.
    if minimum_fee_yen is not None and minimum_fee_yen < 0:
        raise ValueError("ホテル泊の最低請求額は0以上")
    total = Decimal(0)
    for group, member_bases in TABLE.items():
        for week, member_base in enumerate(member_bases):
            price_weight = (Decimal(str(mix[group]))
                            * Decimal(str(distribution[week//8]))/8)
            if not price_weight:
                continue
            for member, member_weight in ((True, 1-nonmember_share), (False, nonmember_share)):
                if not member_weight:
                    continue
                euro = participant_fee_euro(age, period,
                    display_base_euro=member_base+DISPLAY_TABLE_OFFSET_EURO, member=member,
                    member_discount_full_euro=member_discount_full_euro,
                    nonmember_short_euro=nonmember_short_euro)
                before_minimum = (Decimal(str(euro))*Decimal(str(fx))
                                  - Decimal(str(refund_night))*NIGHTS[period])
                adjusted = hotel_fee_example(age, period,
                    display_base_euro=member_base+DISPLAY_TABLE_OFFSET_EURO, member=member, fx=fx,
                    member_discount_full_euro=member_discount_full_euro,
                    nonmember_short_euro=nonmember_short_euro, refund_night=refund_night,
                    minimum_fee_yen=minimum_fee_yen, short_full_cap=short_full_cap)
                total += price_weight*Decimal(str(member_weight))*(Decimal(str(adjusted))-before_minimum)
    return float(total)


def scenario(label="150人・8日間の暫定基準案", *,
             cohorts: Iterable[Cohort] | None=None,
             age_counts: Mapping[str, Mapping[str, int]] | None=None,
             full=150, first=0, second=0, staff_full=15, capacity=227,
             private_youth_full=19, private_youth_first=0, private_youth_second=0, private_room_limit=19,
             private_addition_night=3000, private_pricing="per_night",
             private_extra_cost_night=0, mix=None, fx=170, distribution=(.5,.3,.2),
             nonmember_share=.7, nonmember_full_euro=50, nonmember_short_euro=None,
             paid_days=3, paid_per_day=40, older_day_share=.5, free_day_person_days=300,
             day_cost=800, lodging_night=1000, meal_price=450, full_meals=21, short_meals=11, heat_full_yen=300,
             hotel_refund_night=2000, hotel_minimum_fee_yen=10000, hotel_short_full_cap=True,
             fixed=4_150_000, tejo=2_000_000, excursion=400_000,
             oomoto_total_yen=None, common_covered_yen=0,
             fee_rate=.038, reserve_rate=.12, helper_recovery_yen=0,
             grants=0, deficit_support=0, auto_hotel_overflow=False):
    """helpers の回収収入は実費/無料を直接円指定し、年齢倍率は決して掛けない。

    非会員割合の既定値は0.7。短期差額の省略値は全日差額×0.7。
    nonmember_full_euroは会員割引額（旧変数名）。変更しても表示基本料金CはTABLE+50で固定。
    基本の見通しは全日150人、年齢8/60/60/22、会員30%。それ以外の人数では年齢内訳を指定する。
    現行の宿泊差引き2000円と個室追加3000円は参加者向け料金。施設宿泊原価1000円は別。
    private_pricing="legacy_half_member_base" は従来25ケース再現用で、現行料金ではない。
    個室追加原価は未見積もりのため0を仮置きする。追加費用が無料と確認された意味ではない。
    外部ホテル代と遠足事業費は本人払いの別会計。本体には遠足支援枠だけを計上。
    """
    mix = dict(MIX_JP if mix is None else mix)
    require_number("大本合計へ移す共通費", common_covered_yen)
    if oomoto_total_yen is not None:
        require_number("大本への宿泊・施設合計", oomoto_total_yen)
    elif common_covered_yen:
        raise ValueError("宿泊・施設合計を指定せずに共通費だけ除くことはできません")
    require_number("共通費", fixed)
    if common_covered_yen > fixed:
        raise ValueError("大本合計へ移す共通費は共通費の元額以下")
    for name, value in (("全日人数", full), ("前半人数", first), ("後半人数", second),
                        ("運営人数", staff_full), ("施設内定員", capacity),
                        ("一人一室の個室販売枠", private_room_limit), ("全日個室人数", private_youth_full), ("前半個室人数", private_youth_first),
                        ("後半個室人数", private_youth_second), ("日帰り1日人数", paid_per_day),
                        ("無料日帰り延べ人数", free_day_person_days),
                        ("全日食数", full_meals), ("短期食数", short_meals), ("日帰り受付日数", paid_days)):
        require_count(name, value)
    for name, value in (("全日暑さ対策費", heat_full_yen), ("個室1泊追加額", private_addition_night), ("個室追加原価", private_extra_cost_night),
                        ("日帰り1人日原価", day_cost), ("施設宿泊1泊原価", lodging_night),
                        ("食事1食原価", meal_price), ("ホテル1泊差引額", hotel_refund_night),
                        ("共通費", fixed), ("TEJO関連費", tejo), ("遠足補助", excursion),
                        ("協力者回収収入", helper_recovery_yen), ("助成金", grants),
                        ("赤字補填", deficit_support), ("全日会員割引", nonmember_full_euro)):
        require_number(name, value)
    require_number("円換算率", fx, strictly_positive=True)
    for name, value in (("非会員割合", nonmember_share), ("日帰り35歳以上割合", older_day_share),
                        ("決済手数料率", fee_rate), ("予備費率", reserve_rate)):
        require_number(name, value, maximum=1)
    require_flag("定員超過時のホテル自動振替", auto_hotel_overflow)
    require_flag("短期ホテル料金の全日上限", hotel_short_full_cap)
    if nonmember_short_euro is None:
        nonmember_short_euro = float(Decimal(str(nonmember_full_euro))*Decimal("0.7"))
    require_number("短期会員差額", nonmember_short_euro)
    if hotel_minimum_fee_yen is not None:
        require_number("ホテル泊の最低請求額", hotel_minimum_fee_yen)
    if cohorts is not None and age_counts is not None:
        raise ValueError("cohortsとage_countsは同時に指定できません")
    if cohorts is None and age_counts is None:
        if (full, first, second) != (150, 0, 0):
            raise ValueError("人数を変更するときは年齢内訳age_countsも指定してください")
        age_counts = {"full": {"16_or_under": 8, "17_24": 60, "25_35": 60, "36_plus": 22}}
    cohorts = list(make_cohorts(full, first, second, age_counts=age_counts) if cohorts is None else cohorts)
    for c in cohorts:
        if c.period not in NIGHTS or c.age not in AGE_FACTOR or c.lodging not in ("onsite", "hotel"):
            raise ValueError(f"不正な参加区分: {c}")
        if type(c.count) is not int or c.count < 0:
            raise ValueError("人数は0以上の整数")
    if paid_days not in (0,1,2,3):
        raise ValueError("有料日帰り受付は現日程の最大3日")
    initial_registration = sum(c.count for c in cohorts)
    if auto_hotel_overflow:
        cohorts, routed = route_capacity_overflow(cohorts, capacity, staff_full)
    else:
        routed = 0
    occupancy = nightly_occupancy(cohorts, staff_full)
    if max(occupancy) > capacity:
        raise ValueError("施設内宿泊が作業仮定の定員を超えています")
    private_counts = {"full": private_youth_full, "first": private_youth_first,
                      "second": private_youth_second}
    for period, count in private_counts.items():
        youth_onsite = sum(c.count for c in cohorts
                          if c.period == period and c.age in YOUTH_AGE_KEYS and c.lodging == "onsite")
        if type(count) is not int or count > youth_onsite:
            raise ValueError("各期の個室人数は施設内の青年一般参加者数以下の整数")
    if private_pricing not in ("per_night", "legacy_half_member_base"):
        raise ValueError("個室料金方式が不正です")
    if private_youth_full > private_room_limit:
        raise ValueError("個室人数が一人一室の販売枠を超えています")
    if private_youth_first or private_youth_second:
        raise ValueError("施設内個室は全日参加者専用。前半・後半の個室人数は0にしてください")
    table_average_euro, table_by_country = average_fee(mix, distribution)
    # 平均額だけが正でも、実際に含めた低料金区分で会員料金が負なら集計しない。
    # 料金は基本額Cに対し単調なので、含めた国・申込時期の最小額を調べればよい。
    lowest_display_euro = min(base+DISPLAY_TABLE_OFFSET_EURO
        for group, values in TABLE.items() if mix[group] > 0
        for week, base in enumerate(values) if distribution[week//8] > 0)
    for age, period in {(c.age, c.period) for c in cohorts if c.count}:
        for member in (True, False):
            participant_fee_euro(age, period, display_base_euro=lowest_display_euro,
                member=member, member_discount_full_euro=nonmember_full_euro,
                nonmember_short_euro=nonmember_short_euro)
    display_avg_euro = table_average_euro + DISPLAY_TABLE_OFFSET_EURO
    avg_euro = display_avg_euro - nonmember_full_euro
    by_country = {g: v+DISPLAY_TABLE_OFFSET_EURO-nonmember_full_euro
                  for g, v in table_by_country.items()}
    avg_yen = avg_euro*fx
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
        "private_youth": (private_youth_full*.5*avg_yen
                          if private_pricing == "legacy_half_member_base" else
                          private_youth_full*private_addition_yen(BASE_AGE_KEY,
                              addition_night=private_addition_night)),
        "nonmember": sum(c.count*nonmember_share*fx*(nonmember_full_euro if c.period == "full"
                                                   else nonmember_short_euro) for c in cohorts),
        "paid_day": paid_days*paid_per_day*(4000+3000*older_day_share),
        "hotel_lodging_credit": -sum(c.count*NIGHTS[c.period]*hotel_refund_night
                                     for c in cohorts if c.lodging == "hotel"),
        "helpers_actual_cost_recovery": helper_recovery_yen,
        "grants": grants,
        "deficit_support": deficit_support,
    }
    if hotel_minimum_fee_yen is not None or hotel_short_full_cap:
        income["hotel_fee_rule_adjustment"] = sum(
            c.count*average_hotel_fee_adjustment_yen(c.age, c.period,
                mix=mix, distribution=distribution, fx=fx, nonmember_share=nonmember_share,
                member_discount_full_euro=nonmember_full_euro,
                nonmember_short_euro=nonmember_short_euro, refund_night=hotel_refund_night,
                minimum_fee_yen=hotel_minimum_fee_yen, short_full_cap=hotel_short_full_cap)
            for c in cohorts if c.lodging == "hotel")
    revenue = sum(income.values())
    # 総額方式では施設内宿泊費を総額の一行へ移し、人数×単価を重ねない。
    # 食事、個室の追加原価（合計の対象外とする感度）、参加者向け宿泊差引きは別。
    cost_kwargs = dict(lodging_night=lodging_night if oomoto_total_yen is None else 0,
                       meal_price=meal_price, full_meals=full_meals,
                       short_meals=short_meals, heat_full_yen=heat_full_yen)
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
    # 部屋単位の料金等が判明すれば更新する。0は追加原価の未計上を表す。
    if private_extra_cost_night:
        components["private_extra_lodging"] = sum(private_counts[p]*NIGHTS[p]
                                                  for p in NIGHTS)*private_extra_cost_night
    # 助成金・赤字補填には参加費の決済手数料を掛けない。基準はいずれも0。
    fee_base = revenue - grants - deficit_support
    expenses = {
        "ordinary_and_staff_variable": sum(components.values()),
        "day_reception": (paid_days*paid_per_day+free_day_person_days)*day_cost,
        "fixed_common": fixed-common_covered_yen, "tejo_support": tejo, "excursion_support": excursion,
        "payment_fees": fee_base*fee_rate,
    }
    if oomoto_total_yen is not None:
        expenses["oomoto_lodging_and_venue_total"] = oomoto_total_yen
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
        "average_by_country_display_basic_euro": {g: v+DISPLAY_TABLE_OFFSET_EURO for g, v in table_by_country.items()},
        "income_yen": income, "variable_expense_components_yen": components,
        "expenses_yen": expenses, "expense_subtotal_before_reserve_yen": subtotal,
        "revenue_yen": revenue, "expenses_total_yen": cost, "balance_yen": revenue-cost,
        # 予算説明資料の集計に使う円単位の要約値。
        "revenue": revenue, "cost": cost, "balance": revenue-cost, "occupancy": occupancy,
        "cohorts": cohort_details, "staff_unit_expenses_yen": staff_unit,
        "assumptions": {
            "fx": fx, "country_mix": mix, "registration_distribution": distribution,
            "capacity": capacity, "private_room_limit": private_room_limit, "private_youth_full": private_youth_full,
            "private_youth_first": private_youth_first, "private_youth_second": private_youth_second,
            "private_pricing": private_pricing, "private_addition_night_yen": private_addition_night,
            "private_extra_cost_night_yen": private_extra_cost_night,
            "private_extra_cost_notice": "個室の追加原価は未見積もり。既定0円は未計上を表し、追加費用なしと確認した意味ではない",
            "lodging_night_yen": lodging_night, "hotel_credit_night_yen": hotel_refund_night,
            "oomoto_total_yen": oomoto_total_yen, "common_before_coverage_yen": fixed,
            "common_covered_yen": common_covered_yen,
            "oomoto_total_notice": "総額方式は宿泊費をまとめ、明示した共通費だけ除く。食事は別。金額・対象日・運営の宿泊・個室・光熱・清掃の範囲は未合意。未指定時は従来の個別積算",

            "hotel_minimum_fee_yen": hotel_minimum_fee_yen,
            "hotel_short_full_cap": hotel_short_full_cap,
            "hotel_fee_rules_notice": "ホテル泊だけに全日・短期共通の最低請求額と、短期は同条件全日ホテル料金までの上限を適用。国・週・会員ごとに判定してから平均する。None/Falseは過去比較用に最低額・上限なし",
            "meal_price_yen": meal_price, "full_meal_allowance": full_meals,
            "short_meal_allowance": short_meals, "meal_counts_are_confirmed": False,
            "heat_full_yen": heat_full_yen, "short_vegetarian_heat_fraction": .5, "nonmember_share": nonmember_share,
            "nonmember_full_euro": nonmember_full_euro, "nonmember_short_euro": nonmember_short_euro,
            "day_older_share": older_day_share, "payment_rate": fee_rate, "reserve_rate": reserve_rate,
            "age_factors": AGE_FACTOR,
            "display_table_offset_euro": DISPLAY_TABLE_OFFSET_EURO,
            "membership_discount_parameter_notice": "nonmember_full_euroは会員割引額（旧変数名）。表示基本料金CはTABLE+50で固定し、割引額の感度変更では動かさない",
            "age_factors_apply_to": "非会員・雑魚寝・食事付き・全日程・25～35歳の表示基本額C",
            "private_addition_basis": ("過去比較用：25～35歳の全日会員料金Bの50%。現行料金ではない"
                if private_pricing == "legacy_half_member_base" else
                f"全日7泊の35歳以下一般参加者専用。1人1泊{private_addition_night}円×7泊={private_addition_night*7}円。前半・後半参加は利用不可。年齢・国・会員・申込週の倍率は掛けない"),
            "lodging_price_notice": "ホテル宿泊差引きは参加者向け料金、lodging_night_yenは施設へ払う原価。連動させず別々に設定する",
            "young_participant_cost_discount": False,
            "site_older_cap": "施設内の36歳以上一般参加者に約2割の目安。分母未定のため人数上限へ変換しない",
            "hotel_older_cap": "施設内と同じ厳しい年齢人数上限なし",
            "hotel_breakfast_automatic_deduction": False,
        },
    }


def hotel_fee_example(age, period, *, display_base_euro=350, member=True, fx=170,
                      refund_night=2000, member_discount_full_euro=50,
                      nonmember_short_euro=None, minimum_fee_yen=10000, short_full_cap=True):
    """ホテル泊は最低10000円、短期は同条件全日料金が上限。ホテル代は本人別払い。"""
    require_number("円換算率", fx, strictly_positive=True)
    require_number("ホテル1泊差引額", refund_night)
    require_flag("短期ホテル料金の全日上限", short_full_cap)
    if minimum_fee_yen is not None:
        require_number("ホテル泊の最低請求額", minimum_fee_yen)
    before_minimum = Decimal(str(participant_fee_euro(age, period,
        display_base_euro=display_base_euro, member=member,
        member_discount_full_euro=member_discount_full_euro,
        nonmember_short_euro=nonmember_short_euro)))*Decimal(str(fx))-NIGHTS[period]*Decimal(str(refund_night))
    fee = before_minimum if minimum_fee_yen is None else max(Decimal(str(minimum_fee_yen)), before_minimum)
    if period != "full" and short_full_cap:
        full = Decimal(str(participant_fee_euro(age, "full",
            display_base_euro=display_base_euro, member=member,
            member_discount_full_euro=member_discount_full_euro)))*Decimal(str(fx))-NIGHTS["full"]*Decimal(str(refund_night))
        if minimum_fee_yen is not None:
            full = max(Decimal(str(minimum_fee_yen)), full)
        fee = min(fee, full)
    return float(fee)



# 金額は円。音響60万円・通信10万円は主催側の予算目安。その他の縮小額は検討中。
COMMON_BUDGETS = {
    "baseline": {"会場・光熱・清掃": 600000, "音響・照明": 800000,
        "通信・Wi-Fi": 100000, "講師・文化企画・材料": 400000,
        "ウェブ・登録等": 200000, "下見・準備会議交通": 450000,
        "救護・安全対応": 300000, "会計・監査": 250000, "広報": 150000,
        "TEJO役員の滞在・会議": 300000, "到着案内": 150000,
        "印刷": 150000, "食堂運営": 300000},
    "lean_proposal": {"会場・光熱・清掃": 450000, "音響・照明": 600000,
        "通信・Wi-Fi": 100000, "講師・文化企画・材料": 300000,
        "ウェブ・登録等": 150000, "下見・準備会議交通": 300000,
        "救護・安全対応": 200000, "会計・監査": 150000, "広報": 100000,
        "TEJO役員の滞在・会議": 200000, "到着案内": 100000,
        "印刷": 100000, "食堂運営": 250000},
}


def build_report():
    assert sum(COMMON_BUDGETS["baseline"].values()) == 4150000
    assert sum(COMMON_BUDGETS["lean_proposal"].values()) == 3000000
    lean = {"fixed": 3000000, "tejo": 1000000, "excursion": 300000}
    specs = [
        ("baseline", "比較用の暫定基準：音響80万円等を維持、一般全日150人・運営15人", {}),
        ("previous_costs_at_150", "比較：150人で以前の支出枠を維持", {"fixed": 4500000, "heat_full_yen": 1000}),
        ("lean_proposal", "追加縮小の検討案：共通費300万・TEJO等100万・遠足支援30万", lean),
        ("lean_private_10", "追加縮小案・有料個室10人", {**lean, "private_youth_full": 10}),
        ("lean_private_0", "追加縮小案・有料個室0人", {**lean, "private_youth_full": 0}),
        ("lean_food_550", "追加縮小案・食事550円", {**lean, "meal_price": 550}),
        ("lean_day_2", "追加縮小案・日帰り受付2日", {**lean, "paid_days": 2}),
        ("lean_member_50", "追加縮小案・会員50%", {**lean, "nonmember_share": .5}),
        ("lean_member_70", "追加縮小案・会員70%", {**lean, "nonmember_share": .3}),
        ("lean_staff_25", "追加縮小案・運営25人", {**lean, "staff_full": 25}),
        ("lean_fx_160", "追加縮小案・1ユーロ160円", {**lean, "fx": 160}),
        ("lean_private_cost_1000", "追加縮小案・個室追加原価1000円/人泊", {**lean, "private_extra_cost_night": 1000}),
        ("lean_higher_facility_cost", "追加縮小案・宿泊1800円/泊・食事1900円/日相当", {**lean, "lodging_night": 1800, "meal_price": 1900/3}),
        ("lean_free_90", "追加縮小案・無料来場90人日への見直し例", {**lean, "free_day_person_days": 90}),
        ("lean_120", "追加縮小案・全日120人、運営15人", {**lean, "full": 120,
            "age_counts": {"full": {"16_or_under": 6, "17_24": 48, "25_35": 48, "36_plus": 18}}}),
        ("lean_combined", "追加縮小案・会員50%・個室10人・食事550円・日帰り2日", {
            **lean, "nonmember_share": .5, "private_youth_full": 10, "meal_price": 550, "paid_days": 2}),
    ]
    # 全て条件付き比較。100万円は主催側の感触で、施設の正式見積ではない。
    # common_covered_yenは既存「会場・光熱・清掃」のうち合計100万円に含むと仮定する額。
    specs.extend([
        ("oomoto_total100_base", "条件付き：宿泊・施設合計100万、従来の会場等60万も全て範囲内", {
            "oomoto_total_yen": 1000000, "common_covered_yen": 600000}),
        ("oomoto_total100_lean", "条件付き：追加縮小案で宿泊・施設合計100万、会場等45万も全て範囲内", {
            **lean, "oomoto_total_yen": 1000000, "common_covered_yen": 450000}),
        ("oomoto_total100_lean_extra10", "条件付き：追加縮小案で宿泊・施設100万、総額外の光熱・清掃等10万", {
            **lean, "oomoto_total_yen": 1000000, "common_covered_yen": 350000}),
        ("oomoto_total120_lean", "条件付き：追加縮小案で宿泊・施設合計120万、会場等45万も範囲内", {
            **lean, "oomoto_total_yen": 1200000, "common_covered_yen": 450000}),
    ])
    rows = []
    for key, label, changed in specs:
        row = scenario(label, **changed)
        row.update(case_id=key, changed_parameters_from_baseline=changed,
            age_composition_is_forecast=True,
            balance_before_reserve_yen=row["revenue_yen"]-row["expense_subtotal_before_reserve_yen"],
            reserve_yen=row["expenses_yen"]["reserve"], balance_after_reserve_yen=row["balance_yen"])
        rows.append(row)
    return {
        "version": VERSION, "revision": REVISION, "date": "2026-09-23",
        "user_confirmed": {"ordinary_full": 150, "days": 8, "staff_is_separate": True,
            "observed_private_rooms": 19, "private_rooms_include_annex": True,
            "complete_private_rooms_by_building": {"lumo": 4, "annex": 15},
            "private_room_counts_are_approximate": True,
            "private_room_count_basis": "主催側の見学後の最新説明。完全個室はLUMO館4室・別館15室程度。従来の合計20室という説明を具体化し、予算では19室を採用",
            "sound_budget_target_yen": 600000, "wifi_budget_target_yen": 100000,
            "heat_budget_target_approx_yen": 50000,
            "equipment_budget_target_notice": "主催側が妥当とした規模の目安。見積・契約額の確定や縮小案全体の承認ではない",
            "short_price_fraction": .7,
            "age_ratio": [5,40,40,15], "member_share": .3,
            "oomoto_reported_charge_basis": "修行の宿泊費＋施設利用費",
            "reported_budget_management": "主催側が伺った意向：青年主体で、TEJOの既存銀行口座と連携して財政管理"},
        "provisional": {"staff_full": 15, "age_counts": [8,60,60,22],
            "hotel_full": 22, "paid_private_people": 19,
            "free_day_person_days": 300, "onsite_capacity_document_total": 227,
            "capacity_is_authorized_for_2028": False,
            "room_allocation_notice": "完全個室はLUMO4室・別館15室程度として19室を採用。有料19人は仮定で、取り置きと希望人数を反映する。旧資料の小部屋8室とは区別し、施設定員227人へ19室分を足さない",
            "heat_notice": "300円/全日人は既存冷房等を使う前提の追加消耗品枠。新規冷房工事や全日分の飲料購入を賄う見積もりではない",
            "lean_proposal_is_approved": False,
            "oomoto_100man_estimate": "主催側の感触であり正式提示額ではない。宿泊＋施設合計・食事別の場合を条件付き比較",
            "oomoto_100man_is_formal_quote": False,
            "common_mix_notice": "国・週・年齢と会員割合の相関は未反映。会員30%を各群へ一律適用"},
        "display_basic_table_euro": {g: [v+50 for v in values] for g, values in TABLE.items()},
        "common_budgets_yen": COMMON_BUDGETS,
        "planning_cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "IJK2028_予算モデル_v8_計算結果_20260923.json"
    target.write_text(json.dumps(build_report(), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(target)
