# Deep research: nang cap Analysis thanh lop tri sat am thanh co insight va benchmark

Ngay lap: 2026-05-04
Repo review: `D:\Workspace\SpeechToInfomation-pr`, branch `feature/architecture-refactor-pr`
Muc tieu: sua tinh trang Analysis hien tai bi trung lap, it insight moi, timeline co du lieu nen co nhung khong hien thi; dong thoi tim repo/benchmark moi phu hop de trien khai analysis trong tong the tri sat am thanh hop phap, evidence-bound va do luong duoc.

## 1. Ket luan ngan

Analysis hien tai khong thieu moi thu o tang schema. Thieu nam o tang bien doi `facts -> events -> timeline -> insights`.

Bang chung code:

- `src/services/analysis_intelligence/extractor.py` da bat duoc nhieu `facts`: phone, email candidate, date_range, money, quantity, payment, request, action, policy.
- `src/services/analysis_intelligence/service.py` lai tao graph voi `relations=[]`, `events=[]`, `claims=[]`.
- `src/services/analysis_intelligence/schemas.py` chi tao `legacy_view.timeline` tu `events`, khong tao timeline tu `date_range`, `time`, `request`, `action`, `policy`.
- `frontend/src/components/AnalysisPanel.tsx` chi render timeline tu `viz.timeline`, nen neu backend khong tao event thi UI khong the hien timeline.

Probe tai repo voi transcript mau:

```text
facts_by_type= {'action': 1, 'date_range': 1, 'payment_method': 1, 'phone': 1, 'policy': 1, 'quantity': 2, 'request': 1}
events= 0 timeline= 0 main_events= 0
date_or_action_facts= [
  ('date_range', 'Khoang thoi gian', 'ngay 15 thang 2 den ngay 16 thang 2'),
  ('payment_method', 'Hinh thuc thanh toan', 'Chuyen khoan'),
  ('request', 'Yeu cau dat phong', 'muon dat 2 phong'),
  ('action', 'Se gui so tai khoan qua email', 'gui toi email cua chi so tai khoan'),
  ('policy', 'Dieu khoan dat phong/hoan huy can doc ky', 'dieu khoan dat phong')
]
```

Do do, viec uu tien khong phai them regex vo toi va. Can them cac lop:

1. `event_assembler`: bien fact/action/date/time thanh `EventItem`.
2. `timeline_builder`: tao hai truc thoi gian, gom `audio_time` va `semantic_time`.
3. `insight_engine`: tao insight co gia tri nghiep vu, khong lap lai fact.
4. `llm_structured_extractor`: trich xuat domain/evidence-bound co schema strict.
5. `case_graph`: hop nhat nhieu file trong cung vu viec thanh temporal graph co provenance.
6. `evaluation_pack`: dataset/metric de chung minh chat luong tri sat am thanh.
7. `analysis_reliability`: dua PhoGuard/ASR reliability vao moi fact/event/insight de tranh bien transcript rui ro thanh ket luan.

## 2. Hien trang va diem nghep

### 2.1. Analysis V2 dang dung huong nhung moi la lop fact extraction

Nen tang tot:

- Co `AnalysisGraphV2`, `EvidenceRef`, `review_status`, `schema_version`, `graph_revision`.
- Co `display_sections_vi` de hien thi fact theo nhom.
- Co detail endpoint rieng cho analysis, khong tra transcript trong list/status.
- Co review endpoint, merge/split entity, revision guard.

Diem thieu:

- `EventItem`, `RelationItem`, `ClaimItem` co schema nhung runtime khong tao.
- Domain Template Registry co CRUD/test preview nhung chua tao `slots`/`domain_frames` runtime.
- Frontend chua gui `analysis_mode` va `domain_template_ids` khi Generate Analysis.
- Timeline hien thi phu thuoc `legacy_view.timeline`, ma `legacy_view.timeline` chi lay tu `events`.
- Insight hien tai chu yeu la danh sach fact, khong phai phat hien moi: khong co contradiction, gap, pattern, role, cross-file recurrence, ASR risk propagation.

### 2.2. Vi sao timeline "ro la co nhung khong the hien"

Trong transcript mau co ngay thang, request, action, policy. Extractor da tao `facts`, nhung service khong chuyen chung thanh `events`. Ket qua la UI co `facts` trong "Phan tich tieng Viet" nhung thong ke Timeline = 0.

Day la bug thiet ke, khong phai bug UI don thuan.

## 3. Repo/ky thuat nen dua vao pipeline

### 3.1. Google LangExtract: uu tien P1 cho LLM structured extraction co source grounding

Repo: https://github.com/google/langextract

Ly do phu hop:

- LangExtract tap trung vao trich xuat du lieu co cau truc tu text, voi source grounding den vi tri trong van ban.
- Ho tro few-shot schema, chunking/parallel/multiple passes cho van ban dai.
- Co visualization de review extraction theo context.
- Co canh bao quan trong: extraction khong locate duoc trong source se co `char_interval=None`; pipeline cua du an nen drop hoac mark `requires_review=true`.

Khong nen mo ta la "giam ao giac tuyet doi". Nen dung nhu mot adapter hoac nguon tham khao thiet ke: schema-aware extraction, evidence locator, output visual review.

De xuat:

- P1 khong can vendor ca LangExtract vao core. Tao interface `StructuredExtractionProvider`.
- Provider dau tien co the goi OpenAI Structured Outputs truc tiep; provider thu hai moi la `langextract_adapter`.
- Bat buoc moi item tu LLM co `evidence_text`; server locate lai trong transcript/segment. Neu khong locate duoc thi drop hoac `needs_review`.

### 3.2. GLiNER2: ung vien local IE cho Lite/RTX2050

Repo: https://github.com/fastino-ai/GLiNER2

Ly do phu hop:

- Mot model 205M cho entity extraction, text classification, structured data extraction va relation extraction.
- Thiet ke schema-driven, co the chay CPU/local, khong phu thuoc API ngoai.
- License Apache-2.0.
- Phu hop voi Lite edition de bo sung entity/relation candidate ma khong can local LLM 7B/8B.

Rui ro:

- Can benchmark tieng Viet rieng; khong duoc claim tot cho tieng Viet neu chua test.
- Co the dung cho candidate generation, khong dung lam truth.

De xuat:

- P1.5: optional provider `gliner2_local_candidate`.
- Dau vao: transcript segments + schema labels tu domain template.
- Dau ra: `candidate_entities`, `candidate_relations`, confidence, evidence span.
- Chi promote neu dat benchmark internal: entity F1, false positive rate, RTF/RAM.

### 3.3. Graphiti: ung vien P2/P3 cho temporal case graph

Repo: https://github.com/getzep/graphiti

Ly do phu hop:

- Graphiti la temporal context graph: facts/relations co validity window, episode provenance, custom ontology, hybrid search.
- Rat dung voi bai toan "vu viec co nhieu file am thanh": moi transcript/segment la episode; derived facts/relations tro ve episode goc.
- Co tu duy quan trong ma du an dang thieu: khong chi graph tinh tai mot file, ma graph tien hoa theo thoi gian va theo nguon.

Rui ro:

- Can graph backend nhu Neo4j/FalkorDB/Kuzu/Neptune va LLM structured output; qua nang cho Lite P1.
- Neu dua thang vao product se tang dependency va van hanh.

De xuat:

- P2 lab: `scripts/export_analysis_to_graphiti_episode.py`.
- P3 product optional: `CASE_GRAPH_PROVIDER=postgres|graphiti`.
- Truoc mat hoc thiet ke: `episode_id`, `valid_at`, `invalid_at`, `source_episode_refs`, `contradiction_status`.

### 3.4. SpeechEE va Speech Event Extraction: benchmark dung de chuyen tu transcript analysis sang speech intelligence

Repos/paper:

- Towards Event Extraction from Speech with Contextual Clues: https://arxiv.org/abs/2401.15385
- Repo: https://github.com/jodie-kang/SpeechEE
- SpeechEE benchmark paper: https://arxiv.org/abs/2408.09462
- ACL 2025 XLLM SpeechEE shared task: https://xllms.github.io/SpeechEE/

Ly do phu hop:

- Khong chi text event extraction; bai toan la detect predicate va arguments tu speech/audio.
- Repo co cac tap `Speech-ACE05`, `Speech-DuEE`, `Speech-MAVEN`, `Human-MAVEN`, va cac transcript ASR tu Whisper/W2V2.
- Day la benchmark rat gan voi muc tieu "timeline/event extraction tu am thanh", hon cac NER dataset thuan text.
- Shared task 2025 khoa evaluation thanh 3 muc: event trigger/type F1, event argument/role F1, va event quadruple F1. Day la bo metric dung de chuyen "co insight" thanh diem so.

Rui ro:

- Dataset chinh la English/Chinese, khong thay tieng Viet.
- Khong nen import runtime ngay; nen dung lam lab/eval reference.

De xuat:

- P2: tao `scripts/evaluate_speech_event_extraction.py` de map output du an sang format trigger/argument F1.
- Dung SpeechEE de benchmark pipeline speech -> ASR -> event extraction vs transcript-only.
- Dung internal Vietnamese gold set de quyet dinh product.
- UI timeline nen map truc tiep tu event schema: `event_type`, `trigger_text`, `arguments`, `audio_time`, `semantic_time`, `evidence_refs`.

### 3.5. OmniEvent: toolkit tham chieu cho event detection/argument extraction

Repo: https://github.com/THU-KEG/OmniEvent

Ly do phu hop:

- Toolkit event extraction modular, co event detection va event argument extraction.
- Ho tro English/Chinese, nhieu paradigm va unified evaluation.
- Co dataset list nhu MAVEN, ACE, DuEE, LEVEN, FewFC.

Rui ro:

- Khong phai speech-first, dependency co the nang.
- Khong co tieng Viet mac dinh.

De xuat:

- Khong dua vao runtime P1.
- Dung de thiet ke schema/event argument model va evaluation format.
- Neu can fine-tune sau nay, dung OmniEvent o lab rieng, export model/metric vao manifest.

### 3.6. DCASE 2025, pyannote, BEATs/PANNs, OpenFLAM: lop acoustic intelligence ngoai transcript

Nguon:

- DCASE 2025 Challenge: https://dcase.community/challenge2025/
- DCASE 2025 Task 3 SELD: https://dcase.community/challenge2025/task-stereo-sound-event-localization-and-detection-in-regular-video-content
- DCASE 2025 Task 4 Spatial Semantic Segmentation: https://dcase.community/challenge2025/task-spatial-semantic-segmentation-of-sound-scenes
- DCASE 2025 Task 5 Audio Question Answering va Task 6 Language-Based Audio Retrieval: https://dcase.community/challenge2025/
- pyannote Community-1: https://huggingface.co/pyannote/speaker-diarization-community-1
- BEATs: https://github.com/microsoft/unilm/tree/master/beats
- PANNs: https://github.com/qiuqiangkong/audioset_tagging_cnn
- OpenFLAM/FLAM ICML 2025: https://github.com/adobe-research/openflam

Ly do phu hop:

- Tri sat am thanh khong chi la noi dung loi noi. Can biet co speech/non-speech, overlap, speaker turns, tieng go cua, tieng buoc chan, tieng chuong, tieng go phim, tieng xe, v.v.
- DCASE Task 3 do event detection + temporal activity + localization; Task 4 do detect/separate sound events trong mixture co nhieu su kien.
- pyannote Community-1 co benchmark DER tren AMI/CALLHOME/VoxConverse va co exclusive diarization de reconcile voi transcription timestamps.
- OpenFLAM la huong moi cho open-vocabulary sound event detection/localization bang text query tu do. Diem manh la co the hoi "co tieng go cua/chuong/typing/xe may khong va xuat hien luc nao", thay vi chi nhan cac class co dinh.

Rui ro:

- OpenFLAM code/model dung Adobe Research License non-commercial; chi dua vao lab, khong dua runtime san pham neu chua clear license.
- FLAM yeu cau audio 48kHz trong example va co dependency PyTorch; khong phu hop Lite default RTX2050 neu chua benchmark.

De xuat:

- P1: khong them SED runtime neu chua can; it nhat them `audio_observations` schema.
- P2: optional `sound_event_provider` bang BEATs/PANNs/AudioSet tags, chi luu nhan va thoi diem, confidence, evidence audio span.
- P2 benchmark bang DCASE/FSD50K/ESC-50/MUSAN + internal audio.
- P3 lab OpenFLAM cho query-based acoustic observation; chi hien thi nhu "machine-suggested audio observation", khong suy dien y do hoac hanh vi.

### 3.7. ASR hallucination/reliability phai tro thanh input cua Analysis

Nguon:

- Investigation of Whisper ASR Hallucinations Induced by Non-Speech Audio, ICASSP 2025: https://arxiv.org/abs/2501.11378
- Calm-Whisper, Interspeech 2025: https://arxiv.org/abs/2505.12969

Ly do phu hop:

- Nhom BoH cho thay non-speech co the tao cac hallucination lap lai va co the loc hau xu ly nhu mot safeguard.
- Calm-Whisper cho thay hallucination tren non-speech co lien quan den mot so attention heads va co the giam bang fine-tune, nhung day la model fork/lab, khong phai P1 runtime.

Tac dong den Analysis:

- Moi fact/event/insight phai ke thua `asr_reliability` tu segment: `accepted|needs_review|abstained|unknown`.
- Neu segment co speech_ratio thap, overlap speech, PhoGuard needs_review, hoac non-speech hallucination match BoH, item phai `requires_review=true`.
- Insight quan trong phai co `supporting_item_ids` va `risk_context`; khong duoc nang mot doan ASR rui ro thanh ket luan.
- Benchmark phai do rieng false insight tren non-speech/noise, khong chi do fact recall tren transcript sach.

## 4. Kien truc Analysis moi

### 4.1. Doi ten tu Visualization sang Analysis trong backend contract

Giu compatibility endpoint `/visualize`, nhung runtime nen co service moi:

```text
src/services/analysis_intelligence/
  pipeline.py
  fact_extractor.py              # deterministic core hien co
  event_assembler.py             # facts/actions -> events
  temporal_normalizer.py         # date/time/date_range -> semantic_time
  relation_builder.py            # person-phone, request-target, payment-for-booking
  insight_engine.py              # contradiction/gap/pattern/priority
  structured_llm_extractor.py    # strict schema + evidence_text
  evidence_locator.py            # locate text -> segment/audio timestamp
  providers/
    openai_structured.py
    langextract_adapter.py
    gliner2_adapter.py
  evaluation/
    metrics.py
    fixtures.py
  reliability.py
```

### 4.2. Graph schema nen nang len `analysis_intelligence.v3`

Giu V2 compatibility, nhung them cac truong:

```json
{
  "events": [
    {
      "id": "evt_...",
      "event_type": "booking_request|payment_commitment|information_delivery|policy_notice|meeting|call|threat|transfer",
      "trigger_text": "muon dat 2 phong",
      "label_vi": "Yeu cau dat phong",
      "audio_start_time": 12.4,
      "audio_end_time": 16.8,
      "semantic_time": {
        "kind": "date_range",
        "start": "2026-02-15",
        "end": "2026-02-16",
        "precision": "day",
        "source_fact_id": "fact_date_range_..."
      },
      "speaker_id": "SPEAKER_00",
      "argument_ids": ["arg_..."],
      "evidence_refs": [],
      "review_status": "needs_review"
    }
  ],
  "temporal_links": [
    {
      "source_event_id": "evt_request",
      "target_event_id": "evt_payment",
      "type": "before|after|during|same_time|causes|enables",
      "evidence_refs": []
    }
  ],
  "insights": [
    {
      "id": "insight_missing_required",
      "type": "missing_required_slot|contradiction|timeline_gap|high_value_fact|asr_risk|cross_file_recurrence",
      "severity": "low|medium|high|critical",
      "title_vi": "Thieu thong tin CCCD xac thuc",
      "description_vi": "...",
      "supporting_item_ids": [],
      "evidence_refs": [],
      "recommended_action_vi": "Kiem tra lai audio tai 00:12-00:18"
    }
  ],
  "audio_observations": [
    {
      "id": "aud_...",
      "type": "speech|music|noise|footsteps|doorbell|typing|overlap_speech",
      "start_time": 0.0,
      "end_time": 2.0,
      "confidence": 0.74,
      "source_method": "pyannote|beats|panns|dcase_model"
    }
  ]
  "reliability": {
    "asr_status": "accepted|needs_review|abstained|unknown",
    "speech_ratio": 0.91,
    "diarization_status": "off|available|needs_review",
    "structured_provider_mode": "off|shadow|enforce",
    "ungrounded_item_count": 0
  }
}
```

### 4.3. Timeline phai co hai truc thoi gian

1. `audio_time`: thoi diem trong file, dung de play clip va review evidence.
2. `semantic_time`: ngay/gio duoc noi trong hoi thoai, dung de dung timeline nghiep vu.

Neu transcript khong co timestamp, van tao timeline item voi `audio_time=null`, `semantic_time` tu date/time fact, va `requires_review=true`.

### 4.4. Insight khong duoc lap lai fact

Insight chi duoc tao khi co suy luan tu nhieu item hoac co rui ro van hanh:

- Missing required slot: template hotel_booking yeu cau `customer_name`, `phone`, `checkin`, `checkout`, `room_count`; thieu truong nao thi insight.
- Contradiction: cung slot co nhieu value khac nhau, vi du gia 3 trieu vs 3.5 trieu cho cung hang phong.
- Timeline gap: co request dat phong nhung khong co event xac nhan/tu choi.
- ASR risk propagation: fact quan trong nam trong segment co PhoGuard `needs_review` hoac overlap speech.
- Cross-file recurrence: so dien thoai/email/nguoi xuat hien o >=2 file trong case.
- High-value action: "chuyen khoan", "gui so tai khoan", "hen gap", "de doa", "giao hang" can dua len hang uu tien.

### 4.5. Phan cap ket qua de UI het trung lap

UI nen tach 4 lop, moi lop co tieu chi rieng:

1. `Facts`: gia tri duoc trich xuat truc tiep, vi du phone, email, money, date.
2. `Events`: hanh dong/su kien co trigger va argument, vi du yeu cau dat phong, gui STK, thong bao dieu khoan.
3. `Timeline`: cach sap xep event theo `audio_time` va `semantic_time`.
4. `Insights`: nhan dinh tong hop tu nhieu facts/events hoac tu risk, vi du thieu xac nhan, mau thuan gia, fact quan trong can nghe lai.

Neu mot dong UI chi lap lai `fact.value` thi khong duoc tinh la insight. Neu insight khong co `supporting_item_ids` thi khong render o muc "Ket luan/Insight"; chi render o muc "Can kiem tra".

## 5. Evaluation data de chung minh "hoan thien tri sat am thanh"

### 5.1. Internal Vietnamese gold set la bat buoc

Tao `tests/fixtures/audio_intelligence_gold/` voi it nhat:

- 20 transcript sach tieng Viet co label:
  - hotel booking
  - financial transfer
  - appointment/meeting
  - complaint/threat
  - unknown domain
- 10 transcript ASR noisy:
  - thieu dau cau
  - sai so dien thoai/email
  - lap tu
  - chen tieng Anh/ten rieng
- 10 negative/no-event:
  - noi chuyen xa giao
  - noise-only transcript do ASR hallucinate
  - prompt injection transcript
- 5 multi-file case:
  - cung phone/email xuat hien nhieu file
  - thong tin mau thuan giua hai file

Moi fixture can co:

```json
{
  "transcript": "...",
  "segments": [{"id": "seg_1", "start": 0.0, "end": 3.2, "speaker": "SPEAKER_00", "text": "..."}],
  "gold_facts": [],
  "gold_events": [],
  "gold_relations": [],
  "gold_timeline": [],
  "gold_insights": [],
  "negative_expectations": []
}
```

Metrics:

- Fact/entity exact F1 theo `(type, normalized_value)`.
- Event trigger F1 va event argument F1.
- Event quadruple F1 theo SpeechEE shared task: `trigger + event_type + argument_role + argument_mention`.
- Timeline item F1, temporal order accuracy, date normalization accuracy.
- Insight precision@K, vi insight sai gay hai hon fact thieu.
- Evidence grounding rate: `% item co evidence span locate duoc`.
- Ungrounded structured extraction rate.
- False insight rate tren non-speech/noise.
- Review burden: so item `needs_review`/phut audio.
- False positive traps: CCCD vs phone, organization "khach san minh", date overlap.
- Runtime: RTF, RAM peak, VRAM peak tren RTX2050.

### 5.2. Public benchmark nen dung dung vai tro

- SLUE: spoken NER/sentiment/ASR; dung de do NER tren speech transcript voi metric WER/F1, khong thay the benchmark nghiep vu tieng Viet.
- Speech-based Slot Filling ACL 2024/SLURP: dung de thiet ke slot filling robust voi ASR noise.
- SpeechEE: dung de do event extraction tu speech va ASR transcript, dac biet trigger/argument.
- MAVEN/ACE/DuEE/OmniEvent: dung de thiet ke event schema va evaluation format, khong claim tieng Viet.
- DCASE 2025 Task 3/4: dung cho acoustic event/localization/separation, khong phai semantic transcript analysis.
- pyannote benchmark: dung DER/JER cho speaker diarization va timestamp reconciliation.
- MUSAN/silence/noise: tiep tuc dung cho hallucination/false-speech guard, khong dung lam ground truth nghiep vu.

## 6. Roadmap trien khai

### Phase A: sua Analysis hien tai de co timeline/insight thuc dung

1. Tao `event_assembler.py`.
   - Input: `segments`, `facts`, `entities`, `risk_flags`.
   - Output: `events`, `claims`, `relations`.
   - Mapping ban dau:
     - `request` -> `booking_request|generic_request`
     - `action` -> `information_delivery|follow_up_action`
     - `payment_method` + money -> `payment_discussion`
     - `policy` -> `policy_notice`
     - `date_range` -> semantic time for nearest request/booking event.
   - Moi event bat buoc co:
     - `trigger_text`
     - `event_type`
     - `evidence_refs`
     - `source_fact_ids`
     - `requires_review` ke thua tu fact/segment reliability.
2. Tao `timeline_builder.py`.
   - Build timeline tu `events`.
   - Neu chua co event, tao timeline fallback tu `date_range`, `date`, `time`, `action`, `request`.
   - Khong tao event "Sự kiện lúc X" chung chung.
3. Tao `insight_engine.py`.
   - Missing required facts.
   - Conflict values.
   - ASR/PII review risks.
   - Cross-file recurrence placeholder cho case-level sau.
   - Moi insight bat buoc co `supporting_item_ids`; khong co thi khong render.
4. Update `AnalysisGraphV2` hoac chuan bi V3.
   - Ngan han: dung `events`, `claims`, `relations` co san trong V2.
   - Them `insights` co the la field optional moi neu chua muon bump schema.
5. Test:
   - Transcript mau co `timeline.length >= 4`.
   - `main_events` khong rong.
   - Date range khong tao date duplicate.
   - Moi event co evidence refs.
   - Non-speech/noisy transcript khong tao high-confidence insight.

### Phase B: domain template runtime that su

1. Frontend load `/api/v1/analysis/templates`.
2. UI co selector "Mau phan tich".
3. `handleGenerateAnalysis` gui:

```json
{
  "visualization_type": "all",
  "analysis_mode": "selected",
  "domain_template_ids": [1]
}
```

4. Backend deterministic slot filler:
   - Map slot synonyms/type -> facts da co.
   - Tao `slots` va `domain_frames` truoc khi dung LLM.
5. Insight missing required slots dua vao UI.

### Phase C: structured extraction provider

1. Them config:

```env
ANALYSIS_STRUCTURED_PROVIDER=off|openai|langextract|gliner2_local
ANALYSIS_STRUCTURED_MODE=shadow|enforce
ANALYSIS_STRUCTURED_MAX_INPUT_CHARS=24000
ANALYSIS_STRUCTURED_TIMEOUT_SECONDS=60
ANALYSIS_STRUCTURED_REQUIRE_EVIDENCE=true
ANALYSIS_STRUCTURED_DROP_UNGROUNDED=true
```

2. OpenAI provider:
   - Dung Structured Outputs `json_schema`, `strict=true`.
   - Pydantic validate.
   - Locate `evidence_text` lai trong transcript.
   - Khong log prompt/transcript/raw response.
3. LangExtract adapter:
   - Dung cho long transcript va HTML review artifact trong lab.
   - Drop item khong co `char_interval`.
4. GLiNER2 adapter:
   - Optional local candidate.
   - Chi bat sau benchmark.

Contract provider:

```python
class StructuredExtractionProvider:
    def extract(self, *, text: str, segments: list[SegmentUnit], schema: dict) -> StructuredExtractionResult:
        ...
```

`StructuredExtractionResult` chi duoc merge vao graph khi:

- Pydantic validate pass.
- Moi item co `evidence_text`.
- `evidence_text` locate duoc vao transcript hoac segment.
- Provider chay trong `shadow` khong overwrite deterministic graph.

### Phase D: case-level temporal graph

1. Tao `CaseAnalysisGraph`.
   - Hop nhat nhieu `AnalysisGraphV2/V3`.
   - Canonical entity theo normalized phone/email/person/location.
   - Event timeline theo `semantic_time` va `audio_time`.
2. Tao insights cross-file:
   - Same phone across files.
   - Conflicting price/date/name.
   - Repeated organization/person.
   - Suspicious gap: nhieu request nhung khong co confirm.
3. Lab Graphiti:
   - Export moi transcript segment thanh episode.
   - So sanh native Postgres graph vs Graphiti temporal graph.
   - Khong dua Neo4j/FalkorDB vao Lite mac dinh.

### Phase E: acoustic event layer

1. Them schema `audio_observations`.
2. Provider dau tien:
   - `pyannote`: speech turns, overlap, speaker count.
   - `sound_event_provider=off` mac dinh.
3. Lab BEATs/PANNs/DCASE:
   - Detect speech/noise/music/footsteps/doorbell/typing/cough.
   - Chi show nhu observation, khong suy dien noi dung nghiep vu.

## 7. Repo nao nen clone/tai ve

Khong clone truc tiep vao product tree. Nen tao lab rieng:

```text
external/research_repos/
  langextract/
  GLiNER2/
  SpeechEE/
  OmniEvent/
  graphiti/
```

Manifest:

```json
{
  "repo": "https://github.com/google/langextract",
  "commit": "...",
  "license": "...",
  "purpose": "schema/evidence-grounded extraction research",
  "runtime_in_product": false,
  "validation_status": "research_only"
}
```

Thu tu clone neu can lab:

1. `google/langextract` - uu tien nhat cho evidence-grounded extraction.
2. `fastino-ai/GLiNER2` - local candidate extraction tren RTX2050/CPU.
3. `jodie-kang/SpeechEE` - benchmark speech event extraction.
4. `THU-KEG/OmniEvent` - event schema/evaluation reference.
5. `getzep/graphiti` - temporal case graph lab, khong P1 runtime.
6. `adobe-research/openflam` - lab acoustic observation only, can license review truoc moi su dung ngoai research.

## 8. Acceptance criteria

P0/P1 chi duoc coi la dat khi:

- Transcript hotel sample tao duoc:
  - facts khong duplicate,
  - events >= 4,
  - timeline >= 4,
  - at least 1 missing/verification insight neu thieu slot bat buoc,
  - moi item co evidence_refs.
- UI hien Timeline sau Generate Analysis va sau reload.
- Domain selector gui request that va tao `domain_frames`.
- LLM/structured provider shadow mode khong overwrite deterministic graph.
- Ungrounded LLM item bi drop hoac `needs_review`.
- Tests co negative traps.
- Benchmark report co:
  - fact F1,
  - event trigger/argument F1,
  - timeline order accuracy,
  - insight precision@K,
  - evidence grounding rate,
  - false insight rate tren non-speech/noise,
  - RTF/RAM/VRAM.

## 10. Thu tu uu tien thuc dung

Khong nen bat dau bang clone repo hay them LLM provider. Thu tu dung la:

1. Sua deterministic core truoc: `facts -> events -> timeline -> insights`.
2. Them test gold Vietnamese nho de chung minh UI co timeline va insight khong lap fact.
3. Them structured provider o shadow mode, dung evidence locator de chan hallucination.
4. Sau khi co metric moi clone/research lab GLiNER2, LangExtract, SpeechEE, Graphiti, OpenFLAM.
5. Chi promote provider neu co manifest: commit/SHA/license/model/version/metric/runtime.

## 9. Nguon doi chieu

- Google LangExtract: https://github.com/google/langextract
- Google LangExtract docs: https://developers.google.com/health-ai-developer-foundations/libraries/langextract
- GLiNER2: https://github.com/fastino-ai/GLiNER2
- Graphiti: https://github.com/getzep/graphiti
- SpeechEE contextual clues: https://arxiv.org/abs/2401.15385
- SpeechEE benchmark: https://arxiv.org/abs/2408.09462
- SpeechEE repo: https://github.com/jodie-kang/SpeechEE
- OmniEvent: https://github.com/THU-KEG/OmniEvent
- MAVEN dataset: https://github.com/THU-KEG/MAVEN-dataset
- Speech-based Slot Filling using LLMs: https://aclanthology.org/2024.findings-acl.379/
- SLUE tasks: https://asappresearch.github.io/slue-toolkit/slue-tasks.html
- DCASE 2025 Challenge: https://dcase.community/challenge2025/
- DCASE 2025 Task 3 SELD: https://dcase.community/challenge2025/task-stereo-sound-event-localization-and-detection-in-regular-video-content
- DCASE 2025 Task 4 Spatial Semantic Segmentation: https://dcase.community/challenge2025/task-spatial-semantic-segmentation-of-sound-scenes
- pyannote Community-1: https://huggingface.co/pyannote/speaker-diarization-community-1
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
