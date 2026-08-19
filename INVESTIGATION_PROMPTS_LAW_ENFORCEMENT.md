# INVESTIGATION PROMPTS - LAW ENFORCEMENT USE CASE

**Date:** 2026-01-08
**Purpose:** Prompts tối ưu cho điều tra trinh sát công an
**Focus:** Khai thác tối đa thông tin từ hội thoại để phục vụ điều tra tội phạm

---

## 🎯 YÊU CẦU PHÂN TÍCH ĐIỀU TRA

### **Mục tiêu:**
1. ✅ Không giới hạn độ dài tóm tắt (chi tiết càng tốt)
2. ✅ Trích xuất TẤT CẢ thông tin nhạy cảm (số điện thoại, CCCD, địa chỉ, tài khoản)
3. ✅ Phát hiện dấu hiệu bất thường, hành vi nghi vấn
4. ✅ Phân tích mối quan hệ ẩn, timeline chi tiết
5. ✅ Phát hiện tiếng lóng, mật ngữ, mã hóa
6. ✅ Phân tích tâm lý, cảm xúc, thái độ
7. ✅ Điểm mâu thuẫn, cần làm rõ thêm

---

## 📋 PROMPT 1: INVESTIGATION SUMMARY (Chi tiết không giới hạn)

### **File:** `src/services/summarization/summary_service_v2.py`
### **Location:** Lines 79-91 (investigation type)

```python
elif summary_type == "investigation":
    prompt = f"""
PHÂN TÍCH HỘI THOẠI CHO ĐIỀU TRA HÌNH SỰ

Bạn là chuyên gia phân tích hội thoại phục vụ điều tra tội phạm. Hãy phân tích cuộc hội thoại sau một cách CHI TIẾT, TOÀN DIỆN, KHÔNG GIỚI HẠN ĐỘ DÀI.

=== YÊU CẦU PHÂN TÍCH ===

1. TÓM TẮT TOÀN DIỆN (KHÔNG GIỚI HẠN TỪ):
   - Tóm tắt đầy đủ toàn bộ nội dung hội thoại
   - Không bỏ sót chi tiết nào, dù nhỏ
   - Mô tả rõ ràng ngữ cảnh, mục đích cuộc trò chuyện

2. THÔNG TIN NHÂN THÂN (CRITICAL - ƯU TIÊN CAO):
   ★ Họ tên đầy đủ của tất cả người tham gia
   ★ Số điện thoại (tất cả số xuất hiện)
   ★ Số CCCD/CMND/Hộ chiếu
   ★ Địa chỉ cụ thể (số nhà, đường, phường, quận, thành phố)
   ★ Email
   ★ Ngày sinh, tuổi
   ★ Nghề nghiệp, nơi làm việc
   ★ Biển số xe (nếu có)
   ★ Tài khoản ngân hàng/ví điện tử

3. THÔNG TIN TÀI CHÍNH:
   - Số tiền giao dịch (chính xác đến đồng)
   - Phương thức thanh toán
   - Thông tin tài khoản ngân hàng (số TK, ngân hàng, chủ TK)
   - Lịch sử giao dịch được nhắc đến
   - Khoản nợ, khoản vay, ưu đãi tài chính

4. THỜI GIAN & ĐỊA ĐIỂM:
   - Thời điểm cuộc gọi (nếu xác định được)
   - Tất cả thời gian được nhắc đến (ngày, giờ, khoảng thời gian)
   - Địa điểm cụ thể (tên khách sạn, nhà hàng, địa chỉ, tọa độ nếu có)
   - Lịch trình di chuyển

5. HÀNH ĐỘNG & GIAO DỊCH:
   - Tất cả hành động được thực hiện hoặc hẹn thực hiện
   - Thỏa thuận, cam kết
   - Điều kiện giao dịch
   - Quy trình thanh toán
   - Bước tiếp theo sau cuộc gọi

6. MỐI QUAN HỆ:
   - Quan hệ giữa các bên (khách hàng-nhân viên, bạn bè, đối tác, v.v.)
   - Người thứ ba được nhắc đến (tên, vai trò)
   - Tổ chức liên quan (công ty, đơn vị)
   - Mối liên hệ ẩn (nếu phát hiện)

7. DẤU HIỆU BẤT THƯỜNG (CRITICAL):
   ⚠️ Thái độ không bình thường (lo lắng, vội vã, nghi ngờ)
   ⚠️ Mâu thuẫn trong lời nói
   ⚠️ Thông tin không nhất quán
   ⚠️ Từ chối cung cấp thông tin
   ⚠️ Yêu cầu bí mật, không muốn để lại dấu vết
   ⚠️ Giao dịch bất thường (số tiền lớn, phương thức lạ)
   ⚠️ Hành vi vội vã, thay đổi kế hoạch đột ngột
   ⚠️ Ngôn ngữ mã hóa, tiếng lóng, ẩn ý

8. TIẾNG LÓNG, MẬT NGỮ, MÃ HÓA:
   - Phát hiện từ ngữ lạ, không thông dụng
   - Ẩn ý, ngụ ý trong câu nói
   - Mã số, biệt danh
   - Ngôn ngữ ngầm (VD: "đồ", "hàng", "deal", v.v.)

9. CÁC BÊN THAM GIA:
   Với mỗi người:
   - Vai trò trong cuộc gọi
   - Thái độ, cảm xúc (bình tĩnh, lo lắng, hài lòng, tức giận)
   - Mức độ hợp tác
   - Thông tin họ cung cấp/giấu giếm

10. RỦI RO & CẢNH BÁO:
    🚨 Nguy cơ tội phạm (lừa đảo, rửa tiền, buôn lậu, v.v.)
    🚨 Dấu hiệu hoạt động phi pháp
    🚨 Thông tin cần xác minh khẩn cấp
    🚨 Mối đe dọa an ninh

11. ĐIỂM CẦN LÀM RÕ:
    - Thông tin còn thiếu
    - Mâu thuẫn cần điều tra thêm
    - Câu hỏi cần truy vấn thêm
    - Đối tượng/địa điểm cần giám sát

12. GHI CHÚ ĐIỀU TRA:
    - Đánh giá tổng quan về cuộc gọi
    - Mức độ nguy hiểm (thấp/trung bình/cao)
    - Khuyến nghị hành động tiếp theo
    - Ưu tiên điều tra

=== HỘI THOẠI CẦN PHÂN TÍCH ===

{transcript}

=== HƯỚNG DẪN TRẢ LỜI ===

Hãy viết phân tích CHI TIẾT, KHÔNG GIỚI HẠN ĐỘ DÀI. Mỗi mục trên phải được phân tích đầy đủ. Nếu không có thông tin cho mục nào, ghi rõ "Không có thông tin" hoặc "Cần xác minh thêm".

ƯU TIÊN: Thông tin nhân thân (họ tên, số điện thoại, CCCD, địa chỉ) phải được trích xuất đầy đủ và in đậm.

PHÂN TÍCH ĐIỀU TRA:
"""
```

---

## 📋 PROMPT 2: CONTEXT ANALYSIS - STRUCTURED JSON (Chi tiết tối đa)

### **File:** `src/services/summarization/models/llm_manager.py`
### **Location:** Lines 189-203 (analyze_context method)

```python
def analyze_context(self, text: str, model: str = None) -> Dict:
    """
    Phân tích hội thoại cho mục đích điều tra tội phạm
    Trích xuất TẤT CẢ thông tin có thể, không giới hạn
    """
    prompt = f"""
PHÂN TÍCH HỘI THOẠI CHO ĐIỀU TRA HÌNH SỰ - STRUCTURED OUTPUT

Bạn là chuyên gia điều tra tội phạm. Phân tích hội thoại sau và trích xuất TẤT CẢ thông tin có thể.

Trả về kết quả dưới dạng JSON với cấu trúc sau:

{{
  "summary": "Tóm tắt toàn diện không giới hạn độ dài. Bao gồm tất cả chi tiết quan trọng.",

  "context": {{
    "topic": "Chủ đề chính (VD: Đặt phòng khách sạn, Giao dịch mua bán, Trao đổi thông tin)",
    "purpose": "Mục đích cuộc gọi (Giao dịch thương mại, Tư vấn, Thỏa thuận, Điều phối hoạt động)",
    "status": "Trạng thái (Đã hoàn tất, Đang xử lý, Chờ xác nhận, Bị từ chối, Đáng ngờ)",
    "call_type": "Loại cuộc gọi (Bình thường, Khẩn cấp, Bí mật, Đáng ngờ)",
    "risk_level": "low|medium|high|critical - Mức độ rủi ro"
  }},

  "key_points": [
    "Điểm quan trọng 1 - Chi tiết cụ thể",
    "Điểm quan trọng 2 - Số liệu, thời gian cụ thể"
  ],

  "entities": {{
    "people": [
      {{
        "name": "Họ tên đầy đủ",
        "role": "Vai trò (Nhân viên, Khách hàng, Môi giới, Đối tượng nghi vấn)",
        "phone": "Số điện thoại (nếu có)",
        "id_number": "CCCD/CMND (nếu có)",
        "address": "Địa chỉ đầy đủ (nếu có)",
        "dob": "Ngày sinh (nếu có)",
        "occupation": "Nghề nghiệp (nếu có)",
        "workplace": "Nơi làm việc (nếu có)",
        "is_sensitive": true,
        "context": "Ngữ cảnh xuất hiện trong hội thoại",
        "behavior": "Thái độ, hành vi (bình tĩnh, lo lắng, vội vã, nghi ngờ)",
        "suspicion_level": "none|low|medium|high - Mức độ nghi vấn"
      }}
    ],

    "locations": [
      {{
        "name": "Tên địa điểm (Khách sạn, nhà hàng, địa chỉ cụ thể)",
        "address": "Địa chỉ chi tiết (số nhà, đường, phường, quận, thành phố)",
        "type": "Loại (Khách sạn, Nhà riêng, Văn phòng, Địa điểm công cộng, Địa điểm bí mật)",
        "is_sensitive": false,
        "context": "Mục đích đến địa điểm này"
      }}
    ],

    "time": [
      {{
        "value": "Thời gian cụ thể (ngày, giờ)",
        "type": "Loại (Thời điểm gọi, Thời điểm hẹn, Deadline, Khoảng thời gian)",
        "context": "Ngữ cảnh thời gian",
        "is_sensitive": false,
        "urgency": "normal|urgent|critical - Mức độ khẩn cấp"
      }}
    ],

    "organizations": [
      {{
        "name": "Tên tổ chức/công ty",
        "type": "Loại (Khách sạn, Ngân hàng, Công ty, Cơ quan nhà nước)",
        "context": "Vai trò trong hội thoại"
      }}
    ],

    "contact_info": {{
      "phones": [
        {{
          "value": "Số điện thoại chính xác",
          "owner": "Chủ số điện thoại",
          "type": "mobile|landline|unknown",
          "is_sensitive": true,
          "context": "Ngữ cảnh sử dụng số này"
        }}
      ],
      "emails": [
        {{
          "value": "Địa chỉ email",
          "owner": "Chủ email",
          "is_sensitive": true,
          "context": "Mục đích sử dụng email"
        }}
      ],
      "ids": [
        {{
          "value": "Số CCCD/CMND/Hộ chiếu",
          "owner": "Chủ giấy tờ",
          "type": "cccd|cmnd|passport|other",
          "is_sensitive": true,
          "context": "Ngữ cảnh cung cấp"
        }}
      ],
      "bank_accounts": [
        {{
          "account_number": "Số tài khoản",
          "bank_name": "Tên ngân hàng",
          "account_holder": "Chủ tài khoản",
          "is_sensitive": true,
          "context": "Mục đích sử dụng"
        }}
      ],
      "addresses": [
        {{
          "value": "Địa chỉ đầy đủ",
          "owner": "Chủ địa chỉ",
          "type": "home|office|temporary|unknown",
          "is_sensitive": true,
          "context": "Loại địa chỉ"
        }}
      ],
      "vehicles": [
        {{
          "plate_number": "Biển số xe",
          "vehicle_type": "Loại xe",
          "owner": "Chủ xe",
          "is_sensitive": true,
          "context": "Ngữ cảnh nhắc đến"
        }}
      ]
    }}
  }},

  "relationships": [
    {{
      "source": "Người/Tổ chức A",
      "target": "Người/Tổ chức B",
      "label": "Loại quan hệ (Khách hàng, Nhân viên, Đối tác, Bạn bè, Người thân, Đồng phạm nghi vấn)",
      "context": "Chi tiết mối quan hệ",
      "strength": "weak|moderate|strong - Mức độ quan hệ",
      "is_suspicious": false,
      "suspicion_reason": "Lý do nghi ngờ (nếu có)"
    }}
  ],

  "events": [
    {{
      "time": "Thời điểm sự kiện",
      "description": "Mô tả chi tiết sự kiện",
      "action": "Hành động cụ thể",
      "actors": ["Người tham gia 1", "Người tham gia 2"],
      "location": "Địa điểm xảy ra",
      "result": "Kết quả",
      "is_completed": true,
      "is_suspicious": false
    }}
  ],

  "financial_info": {{
    "transactions": [
      {{
        "amount": "Số tiền chính xác (VD: 6000000 VND)",
        "currency": "VND|USD|EUR",
        "purpose": "Mục đích giao dịch",
        "method": "Phương thức (Chuyển khoản, Tiền mặt, Ví điện tử)",
        "payer": "Người trả",
        "receiver": "Người nhận",
        "status": "pending|completed|cancelled",
        "due_date": "Hạn thanh toán (nếu có)",
        "is_suspicious": false,
        "suspicion_reason": "Lý do nghi ngờ (số tiền lớn bất thường, phương thức lạ)"
      }}
    ],
    "debts": [
      {{
        "amount": "Số tiền nợ",
        "debtor": "Người nợ",
        "creditor": "Người cho vay",
        "context": "Ngữ cảnh khoản nợ"
      }}
    ],
    "offers": [
      {{
        "content": "Nội dung ưu đãi/khuyến mãi",
        "value": "Giá trị (nếu có)",
        "conditions": "Điều kiện áp dụng",
        "validity": "Thời hạn hiệu lực"
      }}
    ]
  }},

  "actions": [
    {{
      "actor": "Người thực hiện",
      "action": "Hành động cụ thể",
      "target": "Đối tượng hành động",
      "time": "Thời điểm",
      "status": "completed|pending|planned",
      "is_suspicious": false
    }}
  ],

  "decisions": [
    {{
      "decision_maker": "Người quyết định",
      "decision": "Nội dung quyết định",
      "context": "Ngữ cảnh",
      "impact": "Ảnh hưởng"
    }}
  ],

  "sentiment": {{
    "overall": "positive|negative|neutral|mixed",
    "caller_emotion": "Cảm xúc người gọi (bình tĩnh, lo lắng, vui vẻ, tức giận, sợ hãi, vội vã)",
    "receiver_emotion": "Cảm xúc người nhận",
    "tension_level": "low|medium|high - Mức độ căng thẳng",
    "cooperation_level": "low|medium|high - Mức độ hợp tác",
    "honesty_assessment": "honest|evasive|deceptive|unknown - Đánh giá trung thực"
  }},

  "sensitive_info": [
    {{
      "category": "personal|financial|criminal|confidential",
      "type": "Loại (Số điện thoại, CCCD, Tài khoản, Thông tin tội phạm)",
      "value": "Giá trị cụ thể",
      "owner": "Chủ sở hữu",
      "sensitivity_reason": "Lý do nhạy cảm",
      "context": "Ngữ cảnh xuất hiện",
      "risk_level": "low|medium|high|critical"
    }}
  ],

  "anomalies": [
    {{
      "type": "behavioral|verbal|financial|logical",
      "description": "Mô tả dấu hiệu bất thường",
      "severity": "low|medium|high|critical",
      "evidence": "Bằng chứng cụ thể từ hội thoại",
      "interpretation": "Giải thích tại sao bất thường"
    }}
  ],

  "slang_detected": {{
    "has_slang": true,
    "terms": [
      {{
        "term": "Từ ngữ lóng/mật ngữ",
        "possible_meaning": "Ý nghĩa có thể",
        "context": "Ngữ cảnh sử dụng",
        "suspicion_level": "low|medium|high"
      }}
    ]
  }},

  "hidden_relationships": [
    {{
      "description": "Mô tả mối quan hệ ẩn",
      "involved_parties": ["Bên 1", "Bên 2"],
      "evidence": "Bằng chứng từ hội thoại",
      "suspicion_level": "low|medium|high"
    }}
  ],

  "contradictions": [
    {{
      "statement_1": "Lời nói 1",
      "statement_2": "Lời nói 2 mâu thuẫn",
      "contradiction_type": "factual|temporal|logical",
      "severity": "minor|significant|major"
    }}
  ],

  "risk_assessment": {{
    "overall_risk": "low|medium|high|critical",
    "crime_indicators": [
      {{
        "crime_type": "fraud|money_laundering|smuggling|drug_trafficking|other",
        "confidence": "low|medium|high",
        "indicators": ["Chỉ báo 1", "Chỉ báo 2"]
      }}
    ],
    "urgency": "routine|monitor|investigate|immediate_action",
    "recommended_actions": [
      "Hành động khuyến nghị 1",
      "Hành động khuyến nghị 2"
    ]
  }},

  "insight": [
    "Insight nghiệp vụ 1 - Phân tích sâu",
    "Insight nghiệp vụ 2 - Đánh giá mối liên hệ"
  ],

  "investigation_notes": {{
    "priority_level": "low|medium|high|critical",
    "follow_up_questions": [
      "Câu hỏi cần truy vấn thêm 1",
      "Câu hỏi cần truy vấn thêm 2"
    ],
    "verification_needed": [
      "Thông tin cần xác minh 1",
      "Thông tin cần xác minh 2"
    ],
    "surveillance_targets": [
      "Đối tượng/địa điểm cần giám sát 1",
      "Đối tượng/địa điểm cần giám sát 2"
    ],
    "missing_information": [
      "Thông tin còn thiếu 1",
      "Thông tin còn thiếu 2"
    ],
    "next_steps": [
      "Bước tiếp theo 1",
      "Bước tiếp theo 2"
    ]
  }},

  "metadata": {{
    "call_duration_estimate": "Ước tính thời lượng cuộc gọi",
    "language": "vi|en|mixed",
    "audio_quality_indicators": "Đánh giá chất lượng (rõ ràng, nhiễu, bị che, v.v.)",
    "background_noise": "Tiếng ồn nền (văn phòng, ngoài trời, ồn ào, v.v.)",
    "number_of_speakers": 2,
    "analysis_timestamp": "Thời điểm phân tích"
  }}
}}

=== HỘI THOẠI CẦN PHÂN TÍCH ===

{text}

=== HƯỚNG DẪN QUAN TRỌNG ===

1. Trích xuất TẤT CẢ thông tin có thể, không bỏ sót chi tiết nào
2. Thông tin nhân thân (họ tên, SĐT, CCCD, địa chỉ) là ƯU TIÊN TUYỆT ĐỐI
3. Đánh giá mức độ nghi vấn một cách khách quan
4. Nếu không có thông tin cho trường nào, để [], "", {{}}, hoặc null
5. Tất cả số tiền phải chính xác đến đồng
6. Tất cả thời gian phải cụ thể (ngày/tháng/năm, giờ:phút nếu có)
7. Phát hiện mâu thuẫn, dấu hiệu bất thường là rất quan trọng
8. Đánh giá risk_level và urgency một cách thận trọng

JSON PHÂN TÍCH:
"""

    try:
        response = self.generate(prompt, model=model, temperature=0.2)  # Very low temp for precision
        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{{.*\}}', response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            logger.info(f"[LLM_MANAGER] Investigation analysis complete | fields={len(parsed)} | risk={parsed.get('risk_assessment', {{}}).get('overall_risk', 'unknown')}")
            return parsed
        else:
            logger.warning("[LLM_MANAGER] No JSON found in response")
            return {{"summary": response, "key_points": []}}
    except Exception as e:
        logger.error(f"[LLM_MANAGER] Investigation analysis failed: {{e}}")
        return {{"summary": "", "key_points": []}}
```

---

## 📊 VÍ DỤ OUTPUT MONG ĐỢI

### **Case: Đặt phòng khách sạn (từ ví dụ của bạn)**

```json
{
  "summary": "Cuộc gọi giữa khách hàng (tên Quyên) và nhân viên G.R.P.Marius Hotel Hà Nội để đặt 2 phòng cho 4 người (2 nam, 2 nữ) vào ngày 15-16/02. Tổng chi phí 6 triệu đồng (mỗi phòng 3 triệu/đêm). Khách được cung cấp bữa sáng buffet và miễn phí phòng gym vào thứ tư. Thanh toán bằng chuyển khoản, nhân viên sẽ gửi thông tin tài khoản và điều khoản qua email. Khách cần thanh toán trước 1 đêm để giữ phòng. Không có yêu cầu đặc biệt. Cuộc gọi diễn ra bình thường, không có dấu hiệu bất thường.",

  "context": {
    "topic": "Đặt phòng khách sạn",
    "purpose": "Giao dịch thương mại - Đặt phòng khách sạn cho nhóm khách",
    "status": "Đã hoàn tất đặt phòng, chờ thanh toán xác nhận",
    "call_type": "Bình thường",
    "risk_level": "low"
  },

  "key_points": [
    "Đặt 2 phòng cho 4 người (2 nam, 2 nữ) tại G.R.P.Marius Hotel Hà Nội",
    "Thời gian lưu trú: 15/02 đến 16/02 (1 đêm)",
    "Giá phòng: 3 triệu đồng/phòng/đêm, tổng cộng 6 triệu đồng",
    "Bao gồm: Bữa sáng buffet tự chọn, miễn phí phòng gym vào ngày thứ tư",
    "Phương thức thanh toán: Chuyển khoản",
    "Yêu cầu thanh toán trước 1 đêm (3 triệu đồng) để giữ phòng",
    "Nhân viên sẽ gửi thông tin tài khoản và điều khoản đặt phòng qua email",
    "Không có yêu cầu đặc biệt về phòng hoặc dịch vụ"
  ],

  "entities": {
    "people": [
      {
        "name": "Quyên",
        "role": "Khách hàng - Người đặt phòng",
        "phone": "[CẦN BỔ SUNG TỪ TRANSCRIPT]",
        "id_number": null,
        "address": null,
        "dob": null,
        "occupation": null,
        "workplace": null,
        "is_sensitive": true,
        "context": "Người liên hệ đặt 2 phòng cho nhóm 4 người",
        "behavior": "Bình tĩnh, hợp tác, rõ ràng về yêu cầu",
        "suspicion_level": "none"
      },
      {
        "name": "[Nhân viên khách sạn - tên chưa rõ]",
        "role": "Nhân viên lễ tân/đặt phòng của G.R.P.Marius Hotel",
        "phone": null,
        "id_number": null,
        "address": "G.R.P.Marius Hotel Hà Nội",
        "is_sensitive": false,
        "context": "Người tiếp nhận và xử lý đặt phòng",
        "behavior": "Chuyên nghiệp, cung cấp thông tin đầy đủ",
        "suspicion_level": "none"
      }
    ],

    "locations": [
      {
        "name": "G.R.P.Marius Hotel Hà Nội",
        "address": "Hà Nội, Việt Nam [Địa chỉ cụ thể cần bổ sung nếu có trong transcript]",
        "type": "Khách sạn",
        "is_sensitive": false,
        "context": "Địa điểm lưu trú cho 4 người từ 15-16/02"
      }
    ],

    "time": [
      {
        "value": "15/02 - 16/02 (năm cần xác minh từ transcript)",
        "type": "Khoảng thời gian lưu trú",
        "context": "1 đêm tại khách sạn",
        "is_sensitive": false,
        "urgency": "normal"
      },
      {
        "value": "Thứ tư (trong khoảng 15-16/02)",
        "type": "Ngày sử dụng dịch vụ gym miễn phí",
        "context": "Ngày lưu trú trùng với thứ tư",
        "is_sensitive": false,
        "urgency": "normal"
      }
    ],

    "organizations": [
      {
        "name": "G.R.P.Marius Hotel Hà Nội",
        "type": "Khách sạn",
        "context": "Đơn vị cung cấp dịch vụ lưu trú"
      }
    ],

    "contact_info": {
      "phones": [
        {
          "value": "[SỐ ĐIỆN THOẠI KHÁCH HÀNG QUYÊN - CẦN TRÍCH XUẤT TỪ TRANSCRIPT]",
          "owner": "Quyên (Khách hàng)",
          "type": "mobile",
          "is_sensitive": true,
          "context": "Số liên lạc để xác nhận đặt phòng"
        },
        {
          "value": "[SỐ ĐIỆN THOẠI KHÁCH SẠN - NẾU CÓ TRONG TRANSCRIPT]",
          "owner": "G.R.P.Marius Hotel",
          "type": "landline",
          "is_sensitive": false,
          "context": "Số hotline đặt phòng"
        }
      ],
      "emails": [
        {
          "value": "[EMAIL KHÁCH HÀNG - CẦN TRÍCH XUẤT TỪ TRANSCRIPT]",
          "owner": "Quyên (Khách hàng)",
          "is_sensitive": true,
          "context": "Email nhận thông tin tài khoản và điều khoản đặt phòng"
        }
      ],
      "ids": [],
      "bank_accounts": [
        {
          "account_number": "[SỐ TÀI KHOẢN KHÁCH SẠN - SẼ ĐƯỢC GỬI QUA EMAIL]",
          "bank_name": "[TÊN NGÂN HÀNG - SẼ ĐƯỢC GỬI QUA EMAIL]",
          "account_holder": "G.R.P.Marius Hotel Hà Nội",
          "is_sensitive": true,
          "context": "Tài khoản nhận thanh toán đặt phòng"
        }
      ],
      "addresses": [],
      "vehicles": []
    }
  },

  "relationships": [
    {
      "source": "Quyên",
      "target": "G.R.P.Marius Hotel Hà Nội",
      "label": "Khách hàng",
      "context": "Khách hàng đặt phòng qua điện thoại",
      "strength": "weak",
      "is_suspicious": false,
      "suspicion_reason": null
    }
  ],

  "events": [
    {
      "time": "[Thời điểm cuộc gọi - cần xác định từ metadata]",
      "description": "Khách hàng Quyên gọi điện đặt phòng",
      "action": "Yêu cầu đặt 2 phòng cho 4 người",
      "actors": ["Quyên", "Nhân viên khách sạn"],
      "location": "Cuộc gọi điện thoại",
      "result": "Đặt phòng thành công",
      "is_completed": false,
      "is_suspicious": false
    },
    {
      "time": "Sau cuộc gọi",
      "description": "Nhân viên gửi email thông tin tài khoản và điều khoản",
      "action": "Gửi email xác nhận đặt phòng",
      "actors": ["Nhân viên khách sạn"],
      "location": "Email",
      "result": "Chờ khách xác nhận và thanh toán",
      "is_completed": false,
      "is_suspicious": false
    },
    {
      "time": "Trước ngày 15/02",
      "description": "Khách hàng thanh toán đặt cọc 1 đêm",
      "action": "Chuyển khoản 3 triệu đồng",
      "actors": ["Quyên"],
      "location": "Chuyển khoản ngân hàng",
      "result": "Giữ phòng",
      "is_completed": false,
      "is_suspicious": false
    },
    {
      "time": "15/02 - 16/02",
      "description": "Nhóm 4 người lưu trú tại khách sạn",
      "action": "Check-in, sử dụng dịch vụ, check-out",
      "actors": ["Nhóm 4 người (bao gồm Quyên)"],
      "location": "G.R.P.Marius Hotel Hà Nội",
      "result": "Hoàn tất lưu trú",
      "is_completed": false,
      "is_suspicious": false
    }
  ],

  "financial_info": {
    "transactions": [
      {
        "amount": "6000000 VND",
        "currency": "VND",
        "purpose": "Tiền phòng 2 phòng x 1 đêm (bao gồm sáng buffet và gym)",
        "method": "Chuyển khoản",
        "payer": "Quyên",
        "receiver": "G.R.P.Marius Hotel Hà Nội",
        "status": "pending",
        "due_date": "Trước ngày 15/02 (thanh toán trước 1 đêm = 3 triệu để giữ phòng)",
        "is_suspicious": false,
        "suspicion_reason": null
      },
      {
        "amount": "3000000 VND",
        "currency": "VND",
        "purpose": "Đặt cọc giữ phòng (1 đêm)",
        "method": "Chuyển khoản",
        "payer": "Quyên",
        "receiver": "G.R.P.Marius Hotel Hà Nội",
        "status": "pending",
        "due_date": "Trước ngày check-in 15/02",
        "is_suspicious": false,
        "suspicion_reason": null
      }
    ],
    "debts": [],
    "offers": [
      {
        "content": "Bữa sáng buffet tự chọn đã bao gồm trong giá phòng",
        "value": "Included",
        "conditions": "Cho tất cả khách trong phòng",
        "validity": "Ngày lưu trú 15-16/02"
      },
      {
        "content": "Miễn phí sử dụng phòng tập thể dục",
        "value": "Free",
        "conditions": "Vào ngày thứ tư (trong khoảng lưu trú)",
        "validity": "Ngày lưu trú"
      }
    ]
  },

  "actions": [
    {
      "actor": "Quyên",
      "action": "Đặt 2 phòng cho 4 người",
      "target": "G.R.P.Marius Hotel",
      "time": "[Thời điểm cuộc gọi]",
      "status": "completed",
      "is_suspicious": false
    },
    {
      "actor": "Nhân viên khách sạn",
      "action": "Gửi thông tin tài khoản và điều khoản qua email",
      "target": "Email của Quyên",
      "time": "Sau cuộc gọi",
      "status": "pending",
      "is_suspicious": false
    },
    {
      "actor": "Quyên",
      "action": "Xác nhận và thanh toán đặt cọc",
      "target": "Tài khoản khách sạn",
      "time": "Sau khi nhận email",
      "status": "pending",
      "is_suspicious": false
    }
  ],

  "decisions": [
    {
      "decision_maker": "Quyên",
      "decision": "Chọn phòng giá 3 triệu đồng/phòng/đêm",
      "context": "Lựa chọn giá phòng phù hợp với nhóm 4 người",
      "impact": "Tổng chi phí 6 triệu đồng cho 1 đêm"
    },
    {
      "decision_maker": "Quyên",
      "decision": "Thanh toán bằng chuyển khoản",
      "context": "Phương thức thanh toán thuận tiện",
      "impact": "Cần có thông tin tài khoản ngân hàng của khách sạn"
    },
    {
      "decision_maker": "Quyên",
      "decision": "Không có yêu cầu đặc biệt",
      "context": "Chấp nhận điều kiện tiêu chuẩn của khách sạn",
      "impact": "Quy trình đặt phòng đơn giản, nhanh chóng"
    }
  ],

  "sentiment": {
    "overall": "positive",
    "caller_emotion": "Bình tĩnh, rõ ràng, hài lòng với điều kiện",
    "receiver_emotion": "Chuyên nghiệp, thân thiện, hỗ trợ tốt",
    "tension_level": "low",
    "cooperation_level": "high",
    "honesty_assessment": "honest"
  },

  "sensitive_info": [
    {
      "category": "personal",
      "type": "Họ tên",
      "value": "Quyên",
      "owner": "Khách hàng",
      "sensitivity_reason": "Thông tin cá nhân",
      "context": "Tên người đặt phòng",
      "risk_level": "low"
    },
    {
      "category": "personal",
      "type": "Số điện thoại",
      "value": "[CẦN TRÍCH XUẤT TỪ TRANSCRIPT]",
      "owner": "Quyên",
      "sensitivity_reason": "Thông tin liên lạc cá nhân",
      "context": "Số điện thoại để xác nhận đặt phòng",
      "risk_level": "medium"
    },
    {
      "category": "personal",
      "type": "Email",
      "value": "[CẦN TRÍCH XUẤT TỪ TRANSCRIPT]",
      "owner": "Quyên",
      "sensitivity_reason": "Thông tin liên lạc cá nhân",
      "context": "Email nhận thông tin đặt phòng và điều khoản",
      "risk_level": "medium"
    },
    {
      "category": "financial",
      "type": "Thông tin tài khoản ngân hàng",
      "value": "[SẼ ĐƯỢC GỬI QUA EMAIL]",
      "owner": "G.R.P.Marius Hotel",
      "sensitivity_reason": "Thông tin tài chính",
      "context": "Tài khoản nhận thanh toán",
      "risk_level": "high"
    }
  ],

  "anomalies": [],

  "slang_detected": {
    "has_slang": false,
    "terms": []
  },

  "hidden_relationships": [],

  "contradictions": [],

  "risk_assessment": {
    "overall_risk": "low",
    "crime_indicators": [],
    "urgency": "routine",
    "recommended_actions": [
      "Xác nhận số điện thoại và email của khách hàng Quyên từ transcript",
      "Theo dõi thanh toán đặt cọc có được thực hiện đúng hạn không",
      "Lưu lại bản ghi cuộc gọi theo quy định"
    ]
  },

  "insight": [
    "Giao dịch đặt phòng khách sạn hoàn toàn bình thường, không có dấu hiệu bất thường",
    "Khách hàng hợp tác tốt, cung cấp thông tin rõ ràng",
    "Số lượng khách (4 người) và số phòng (2 phòng) phù hợp với mục đích du lịch hoặc công tác nhóm nhỏ",
    "Phương thức thanh toán chuyển khoản là tiêu chuẩn, không đáng ngờ"
  ],

  "investigation_notes": {
    "priority_level": "low",
    "follow_up_questions": [
      "Số điện thoại chính xác của khách hàng Quyên là gì?",
      "Địa chỉ email của khách hàng là gì?",
      "Thông tin CCCD/CMND có được cung cấp khi check-in không? (Tiêu chuẩn khách sạn)"
    ],
    "verification_needed": [
      "Xác minh khách hàng Quyên có thực sự thanh toán đặt cọc không",
      "Xác minh nhóm 4 người có check-in đúng ngày 15/02 không"
    ],
    "surveillance_targets": [],
    "missing_information": [
      "Số điện thoại khách hàng (cần trích xuất từ transcript)",
      "Email khách hàng (cần trích xuất từ transcript)",
      "Thông tin 3 người còn lại trong nhóm 4 (nếu có trong transcript)"
    ],
    "next_steps": [
      "Lưu trữ hồ sơ đặt phòng theo quy định",
      "Không cần hành động điều tra thêm trừ khi có thông tin mới"
    ]
  },

  "metadata": {
    "call_duration_estimate": "3-5 phút (ước tính dựa trên nội dung)",
    "language": "vi",
    "audio_quality_indicators": "Rõ ràng (giả định)",
    "background_noise": "Văn phòng/lễ tân khách sạn (giả định)",
    "number_of_speakers": 2,
    "analysis_timestamp": "2026-01-08"
  }
}
```

---

## 🔧 IMPLEMENTATION CHECKLIST

### **Files to Update:**

- [ ] `src/services/summarization/summary_service_v2.py` (lines 79-91)
  - Replace investigation prompt with PROMPT 1 above

- [ ] `src/services/summarization/models/llm_manager.py` (lines 189-203)
  - Replace analyze_context method with PROMPT 2 above

- [ ] Test with real data
  - Upload audio with sensitive info (phone, CCCD, address)
  - Verify all fields extracted correctly
  - Check anomaly detection works
  - Verify risk assessment accuracy

### **Testing Focus:**

1. **Sensitive Info Extraction:**
   - ✅ Phone numbers (all formats: 0987654321, +84987654321)
   - ✅ CCCD/CMND (12 digits, 9 digits)
   - ✅ Addresses (complete format)
   - ✅ Bank accounts
   - ✅ Email addresses

2. **Anomaly Detection:**
   - ✅ Large unusual transactions
   - ✅ Rushed/urgent tone
   - ✅ Evasive answers
   - ✅ Contradictions
   - ✅ Slang/code words

3. **Risk Assessment:**
   - ✅ Correctly identifies low-risk calls
   - ✅ Flags high-risk indicators
   - ✅ Provides actionable recommendations

---

## 📞 USE CASE EXAMPLES

### **Low Risk: Normal Hotel Booking** (ví dụ của bạn)
- Expected: risk_level = "low", no anomalies, routine urgency

### **Medium Risk: Large Cash Transaction**
- Scenario: Mua bán hàng hóa với số tiền lớn (>50 triệu), thanh toán tiền mặt
- Expected: risk_level = "medium", financial anomaly flagged

### **High Risk: Suspicious Code Language**
- Scenario: Giao dịch với tiếng lóng ("hàng", "đồ", "deal"), vội vã, không muốn để lại dấu vết
- Expected: risk_level = "high", slang_detected, urgency = "investigate"

### **Critical Risk: Human Trafficking Indicators**
- Scenario: Di chuyển nhiều người, địa điểm lạ, yêu cầu bí mật, thanh toán lớn
- Expected: risk_level = "critical", crime_indicators = "human_trafficking", urgency = "immediate_action"

---

## 🎯 SUCCESS CRITERIA

**Prompt được coi là thành công khi:**

1. ✅ **100% thông tin nhạy cảm được trích xuất**
   - Họ tên, SĐT, CCCD, địa chỉ không bị bỏ sót

2. ✅ **Không giới hạn độ dài**
   - Summary đầy đủ, chi tiết, không bị cắt ngắn

3. ✅ **Phát hiện bất thường chính xác**
   - True positive rate > 90%
   - False positive rate < 10%

4. ✅ **Risk assessment khách quan**
   - Low risk: Cuộc gọi bình thường không bị flag sai
   - High risk: Dấu hiệu nghi vấn được phát hiện kịp thời

5. ✅ **Actionable insights**
   - Recommended actions hữu ích
   - Follow-up questions đúng trọng tâm
   - Verification needed cụ thể

---

**Document Created:** 2026-01-08
**Status:** ✅ READY FOR IMPLEMENTATION
**Priority:** 🔴 CRITICAL
**Impact:** 🚀 TRANSFORMATIVE for law enforcement use case

