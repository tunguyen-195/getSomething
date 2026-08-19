"""Scenario focus profiles for evidence-first investigative bulletin extraction."""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Literal, cast


ResolvedInvestigationScenario = Literal[
    "general",
    "financial_asset",
    "coordination_planning",
    "threat_coercion",
    "goods_transport",
    "public_administration",
    "incident_conflict",
]
InvestigationScenario = Literal[
    "auto",
    "general",
    "financial_asset",
    "coordination_planning",
    "threat_coercion",
    "goods_transport",
    "public_administration",
    "incident_conflict",
]

INVESTIGATION_SCENARIOS: Final[tuple[InvestigationScenario, ...]] = (
    "auto",
    "general",
    "financial_asset",
    "coordination_planning",
    "threat_coercion",
    "goods_transport",
    "public_administration",
    "incident_conflict",
)
RESOLVED_INVESTIGATION_SCENARIOS: Final[tuple[ResolvedInvestigationScenario, ...]] = (
    "general",
    "financial_asset",
    "coordination_planning",
    "threat_coercion",
    "goods_transport",
    "public_administration",
    "incident_conflict",
)
DEFAULT_INVESTIGATION_SCENARIO: Final[InvestigationScenario] = "auto"

_COMMON_GUIDANCE: Final[str] = (
    "Trước hết phải tái hiện cuộc trao đổi thành một câu chuyện liền mạch: ai tham gia, "
    "vai trò nào được chính nguồn nêu, vấn đề trung tâm, diễn biến và trạng thái từng sự "
    "kiện, thời gian và địa điểm được mô tả, đối tượng liên quan, quan hệ, số liệu chính "
    "xác, quyết định, kết quả và điểm chưa rõ. Phân biệt nội dung nghe được với nhận định "
    "có giới hạn; không biến lời kể, nghi vấn hoặc kế hoạch thành sự thật đã xác lập."
)

_PROFILE_GUIDANCE: Final[dict[ResolvedInvestigationScenario, str]] = {
    "general": (
        "Tái hiện toàn bộ nội dung mà không ép vào một khuôn chuyên ngành. Giữ câu chuyện "
        "chính, các tình tiết có ý nghĩa, người và đối tượng quan trọng, kết quả, mâu thuẫn "
        "và mọi mức độ không chắc chắn đã được nêu."
    ),
    "financial_asset": (
        "Ưu tiên số tiền, đơn vị tiền, tài khoản, chủ thể được nêu, nguồn và đích, lời hứa, "
        "khoản nợ, thanh toán, dịch chuyển tài sản, trạng thái giao dịch, mục đích và bất "
        "thường được nói rõ. Giữ nguyên từng chữ số và đúng quan hệ chủ thể-giá trị; không "
        "suy diễn giao dịch là bất hợp pháp, gian lận hoặc rửa tiền."
    ),
    "coordination_planning": (
        "Ưu tiên người tham gia và vai trò, mục tiêu được nói rõ, trình tự hành động dự kiến, "
        "phân công, hậu cần, điểm hẹn, thời hạn, kênh liên lạc, đối tượng và quan hệ phụ "
        "thuộc. Tách rõ đề xuất, thống nhất, giao việc, thử thực hiện và đã hoàn thành; "
        "không biến kế hoạch thành hành vi đã xảy ra hoặc tự suy ra đồng phạm, ý chí chung."
    ),
    "threat_coercion": (
        "Ưu tiên nội dung đe dọa hoặc yêu cầu, đúng người phát ngôn và người bị hướng tới, "
        "thời hạn, hành động bị yêu cầu, phương thức được nêu, bối cảnh an toàn, phản ứng và "
        "điểm chưa rõ. Giữ nguyên trạng thái trích dẫn, tố cáo, phủ nhận, điều kiện hoặc mơ "
        "hồ; không suy ra năng lực thực hiện, ý định, mức độ nguy hiểm hay tội lỗi từ giọng nói."
    ),
    "goods_transport": (
        "Ưu tiên hàng hóa hoặc đồ vật, số lượng và đơn vị, bao gói, người đang giữ, phương "
        "tiện, tuyến đường, nguồn và đích, việc bàn giao, thời gian, địa điểm, người tham gia "
        "và trạng thái giao nhận được nêu. Không coi tiếng lóng, bao gói hoặc cách che giấu "
        "là bằng chứng hàng cấm hay tự suy ra quyền sở hữu."
    ),
    "public_administration": (
        "Ưu tiên cơ quan hoặc tổ chức và chức năng, người phụ trách, thủ tục, ngày tháng, "
        "địa điểm, tài liệu, loại biểu mẫu, tỷ lệ hoặc số lượng chính xác, hướng dẫn, quyết "
        "định, ngoại lệ và kết quả. Phân biệt quy định, chỉ đạo và sự việc thực tế đã xảy ra; "
        "không biến sai khác thủ tục thành vi phạm hay dấu hiệu tội phạm."
    ),
    "incident_conflict": (
        "Ưu tiên từng bên liên quan, nguyên nhân được mỗi bên trình bày, trình tự hành động, "
        "thiệt hại hoặc thương tích được nêu, đồ vật, địa điểm, phản ứng, kết quả, mâu thuẫn "
        "và điểm chưa rõ về danh tính hoặc quan hệ nhân quả. Giữ riêng từng lời kể; không tự "
        "phân xử lỗi, trách nhiệm hoặc nguyên nhân từ transcript."
    ),
}

_DETECTION_MARKERS: Final[
    tuple[tuple[ResolvedInvestigationScenario, tuple[tuple[str, int], ...]], ...]
] = (
    (
        "financial_asset",
        (
            ("tài khoản", 4),
            ("chuyển khoản", 4),
            ("triệu đồng", 3),
            ("tỷ đồng", 3),
            ("thanh toán", 2),
            ("vay", 2),
            ("nợ", 2),
        ),
    ),
    (
        "threat_coercion",
        (
            ("đe dọa", 5),
            ("đe doạ", 5),
            ("uy hiếp", 5),
            ("ép buộc", 4),
            ("tống tiền", 5),
            ("nếu không", 2),
            ("giết", 4),
        ),
    ),
    (
        "goods_transport",
        (
            ("giao hàng", 4),
            ("nhận hàng", 4),
            ("vận chuyển", 4),
            ("biển số", 3),
            ("phương tiện", 2),
            ("kiện hàng", 3),
            ("điểm giao", 3),
        ),
    ),
    (
        "public_administration",
        (
            ("bầu cử", 5),
            ("lá phiếu", 5),
            ("thủ tục", 3),
            ("quy trình", 3),
            ("hướng dẫn", 2),
            ("hồ sơ", 2),
            ("cơ quan", 1),
        ),
    ),
    (
        "incident_conflict",
        (
            ("xô xát", 5),
            ("tranh chấp", 4),
            ("tai nạn", 4),
            ("thiệt hại", 3),
            ("bị thương", 4),
            ("mâu thuẫn", 3),
        ),
    ),
    (
        "coordination_planning",
        (
            ("kế hoạch", 4),
            ("phân công", 4),
            ("chuẩn bị", 3),
            ("điểm hẹn", 3),
            ("thống nhất", 2),
            ("đúng giờ", 2),
        ),
    ),
)


def require_investigation_scenario(value: object) -> InvestigationScenario:
    if type(value) is not str and hasattr(value, "default"):
        value = getattr(value, "default")
    if type(value) is not str or value not in INVESTIGATION_SCENARIOS:
        allowed = ", ".join(INVESTIGATION_SCENARIOS)
        raise ValueError(f"Unsupported investigation_scenario {value!r}; allowed: {allowed}")
    return cast(InvestigationScenario, value)


def resolve_investigation_scenario(
    requested: InvestigationScenario,
    transcript: str,
) -> ResolvedInvestigationScenario:
    if requested != "auto":
        return cast(ResolvedInvestigationScenario, requested)
    normalized = _normalize_detection_text(transcript)
    accent_preserving = _normalize_detection_text(transcript, strip_marks=False)
    scores: dict[ResolvedInvestigationScenario, int] = {}
    for scenario, markers in _DETECTION_MARKERS:
        score = sum(
            _count_asserted_marker(
                accent_preserving if marker == "vay" else normalized,
                _normalize_detection_text(
                    marker,
                    strip_marks=marker != "vay",
                ),
            )
            * weight
            for marker, weight in markers
        )
        scores[scenario] = score
    best_score = max(scores.values(), default=0)
    if best_score <= 0:
        return "general"
    winners = [scenario for scenario, score in scores.items() if score == best_score]
    return winners[0] if len(winners) == 1 else "general"


def _normalize_detection_text(value: str, *, strip_marks: bool = True) -> str:
    if not strip_marks:
        return " ".join(value.casefold().split())
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return " ".join(without_marks.split())


def _count_asserted_marker(normalized: str, marker: str) -> int:
    pattern = re.compile(rf"(?<!\w){re.escape(marker)}(?!\w)")
    count = 0
    for match in pattern.finditer(normalized):
        prefix = normalized[max(0, match.start() - 48) : match.start()]
        negation = re.search(r"(?:khong|chua)\s+co\s+([^.;!?]*)$", prefix)
        if (
            negation is not None
            and len(negation.group(1).split()) <= 6
            and re.search(r"\b(?:nhung|tuy nhien|du vay)\b", negation.group(1)) is None
        ):
            continue
        count += 1
    return count


def scenario_prompt_guidance(
    requested: InvestigationScenario,
    transcript: str,
) -> tuple[ResolvedInvestigationScenario, str]:
    resolved = resolve_investigation_scenario(requested, transcript)
    return resolved, f"{_COMMON_GUIDANCE} {_PROFILE_GUIDANCE[resolved]}"


__all__ = [
    "DEFAULT_INVESTIGATION_SCENARIO",
    "INVESTIGATION_SCENARIOS",
    "InvestigationScenario",
    "RESOLVED_INVESTIGATION_SCENARIOS",
    "ResolvedInvestigationScenario",
    "require_investigation_scenario",
    "resolve_investigation_scenario",
    "scenario_prompt_guidance",
]
