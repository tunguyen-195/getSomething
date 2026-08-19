# Investigative Report Summary - Product Implementation Plan

**Ngay chot revision:** 2026-08-11
**Workspace duy nhat:** E:\research\STT
**Goal tong:** P0-P8 active
**Pham vi plan nay:** slice S2-R0 den S2-R9 cua Summary investigation; khong dong
bo nguoc, sua hoac xoa repo D.

## 1. Quyet dinh san pham

Summary khong phai transcript rut gon, danh sach field, evidence preview, hay mot tap
hop cac cau da loc. Dau ra phai la **ban bao cao tom tat bang tieng Viet, viet hoan
toan o ngoi thu ba**, de lanh dao doc va nam duoc cau chuyen cua file audio:

1. ai tham gia va vai tro nao thuc su duoc nguon xac lap;
2. van de trung tam cua cuoc trao doi;
3. dien bien, su kien, hanh dong, quyet dinh va ket qua theo trinh tu co can cu;
4. doi tuong, tai san, tai lieu, phuong tien, dia diem va moi quan he quan trong;
5. ten, thoi gian, so tien, so luong, tai khoan, dien thoai, ma dinh danh va cac
   gia tri chinh xac neu co;
6. cao buoc, phu nhan, dieu kien, mau thuan, ke hoach va muc do chua xac minh;
7. mot nhan dinh gioi han ve ban chat cuoc trao doi neu co du tien de, khong bien
   suy luan thanh su that hay ket luan phap ly.

Than ban tin chi chua noi dung nghe duoc da duoc tong hop. Evidence, offset am
thanh, speaker ID, fact/claim ID, hash, model, prompt, canh bao, disclaimer va ghi
chu ky thuat van duoc giu noi bo de kiem chung nhung tuyet doi khong hien trong
Summary.

## 2. Contract hoan thanh co the kiem chung

Mot Summary chi duoc persist "summarized" khi tat ca gate sau PASS:

- available=true, writer_status=accepted, summary_state=source_grounded_narrative;
- viet o ngoi thu ba; khong con cach xung ho hoi thoai toi/tao/minh/em/anh/chi/ben em
  de thay cho chu the cua bao cao;
- moi nguoi tham gia duoc tham chieu bang public_actor_label co provenance;
- moi hard narrative obligation duoc the hien dung mot lan;
- dung actor/action/object/recipient, attribution, negation, condition, uncertainty,
  planned/completed state va exact values;
- cac su kien co thu tu chi duoc noi bang "sau do", "truoc do", "dong thoi", "do do"
  khi host co temporal/causal edge tuong ung;
- khong chep noi transcript; direct-copy gate PASS sau khi mask ten va exact values;
- khong co ket luan toi pham, dong co, y dinh, danh tinh, quyen so huu hoac quan he
  khong duoc nguon/released assessment ho tro;
- than bao cao co cau ket thuc, lien ket chu the on dinh, khong lap y, khong tieu de,
  bullet, field label hoac metadata;
- hard maximum word bound dat; minimum chi la muc tieu mem. Neu hard obligations
  khong the nam trong gioi han thi fail typed INVESTIGATION_LENGTH_CONFLICT, khong
  truncate va khong am tham demote thong tin quan trong.

grounded_transcript_only, quote_only_fallback, evidence preview, sanitized legacy
text va partial source excerpt khong duoc coi la Summary.

## 3. Audit current-state va root cause

Audit doc lap ngay 2026-08-11 xac nhan:

- validate_public_report_body() hien chap nhan truc tiep cac cau nhu "Chi muon...",
  "Em se gui...", "Minh se duoc..."; gate moi chi chan heading/metadata.
- Prompt hien cam model dung tu noi dung moi va tu dong nghia vang mat trong ledger.
  Quy tac nay day model ve sao chep transcript thay vi viet bao cao tu nhien.
- _writer_context_surfaces() con cap them "chi" nhung khong cap role label co
  provenance nhu "nguoi dat phong", "nhan vien khach san", "nguoi tham gia".
- Planner dang tao qua nhieu slot ngan, thuong gan mot source row thanh mot cau;
  fixture 26 row xen ke tao 26 plan, 0 plan gom nhieu obligation.
- Critic chua co gate cho report voice, entity continuity, chronology, terminal
  punctuation, direct-copy run va row-by-row realization.
- Task live d59205bd-7955-4143-a721-3cb40ca4ba7c duoc danh dau accepted du
  11/14 sentence record con dau vet hoi thoai va muc copy token cao.
- Task cd6f85d0-ac0a-438d-86b1-a1df43d0767d van fail typed writer rejection vi
  loi sau _apply_bulletin_writer_draft() khong duoc chuyen thanh sentence-scoped
  delta target.
- Auto scenario bo dau tieng Viet lam "vay" va "no" va cham voi marker tai chinh,
  tao false-positive cho financial_asset; cuoc goi dat dich vu bi lech profile.
- Replay verifier hien chi chung minh availability/state/call-count, khong chung minh
  chat luong nghiep vu.

Ket luan: doi model hoac them mot vai cau prompt se khong giai quyet dung goc. Can
doi host planning contract, public actor labels, prompt, deterministic critics va
evaluation gate cung luc.

## 4. Kien truc muc tieu

~~~
Transcript + diarized turns + ASR metadata
        -> immutable source units
        -> typed claims/entities/events/relations/exact values
        -> participant registry + public actor labels
        -> canonical obligation ledger + contradictions
        -> entity/event/timeline chains
        -> adaptive NarrativePacketPlan set
        -> LLM writes paragraph text only
        -> atomic support + voice + chronology + copy + legal critics
        -> bounded repair/delta repair
        -> reader-facing third-person report body
~~~

Audio dai khong duoc xu ly bang cach chi tang context window. Moi source unit co
mot owner chunk; overlap chi dung lam context. Chunk map chi sinh du lieu typed,
khong sinh prose. Host merge/deduplicate toan cuc, giu contradiction/aliases va
lap packet toan cuc truoc khi goi writer.

## 5. Typed contract can them

### 5.1 ParticipantReference

Moi nguoi tham gia/doi tuong duoc lap thanh registry:

- participant_id;
- source_speaker_ids;
- display_name neu ten duoc self-identify hoac source-attributed;
- grounded_roles va evidence refs;
- identity_basis: self_identified, source_attributed, conversation_role, anonymous;
- public_actor_label: ten, vai tro co can cu, hoac alias an toan nhu "mot nguoi
  tham gia", "nguoi goi", "nguoi tiep nhan cuoc goi";
- allowed_reference_forms;
- withheld_identity_reason neu khong du can cu.

LLM khong tu quyet dinh "chi -> khach hang" hay "ben em -> nhan vien khach san".
Host phai cap label va provenance. Neu diarization degraded, label giam xuong
"mot nguoi tham gia" thay vi doan danh tinh hoac so nguoi.

### 5.2 NarrativeObligation

Moi obligation la mot menh de nghiep vu atomic, gom:

- canonical subject, action, object, recipient/source/destination;
- entity/event/value refs;
- exact surfaces;
- source attribution;
- negation, condition, uncertainty, interrogative, planned/completed state;
- temporal/causal edges;
- criticality va coverage_lock;
- scenario tags;
- source-unit refs va source order.

### 5.3 NarrativePacketPlan

Khong tai su dung SummarySentenceRole lam packet role. Packet co contract rieng:

- lede: chu the, van de/su kien trung tam, doi tuong va trang thai;
- participants_objects: nguoi, vai tro, vat/tai san/tai lieu va quan he;
- chronology: chuoi dien bien theo temporal graph hoac source order trung tinh;
- outcome_status: quyet dinh, ket qua, buoc tiep theo, tinh trang hien tai;
- uncertainty: cao buoc, phu nhan, mau thuan va noi dung chua xac minh.

Moi packet giu packet_id, obligation IDs, allowed actor labels, protected atoms,
allowed transitions, target word budget va immutable plan hash. Model chi tra
packet_id va paragraph_text.

## 6. Prompt contract

### 6.1 Vai tro

System prompt dung nghia vu sau:

> Ban la mo-dun soan thao bao cao tom tat nghiep vu. Hay viet theo giong van cua
> can bo sau khi nghe toan bo file audio va bao cao lanh dao, nhung khong tu nhan
> la chu the dieu tra, khong bo sung ket luan phap ly va khong dung kien thuc ngoai
> du lieu da duoc host cung cap.

### 6.2 Chinh sach tu vung hai lop

Khong tiep tuc cam moi tu vang mat trong source. Thay bang:

- **Protected factual atoms:** ten, so, ma, thoi gian, dia diem, su kien, dong tu
  hanh dong, vai tro semantic, attribution va modality phai duoc bao toan.
- **Allowed report language:** model duoc dung lien tu va cum bao cao trung tinh
  nhu "cuoc trao doi tap trung vao", "nguoi nay cho biet", "phia ... xac nhan",
  "tiep do", "ket qua", "noi dung chua duoc lam ro", nhung chi khi packet cho
  phep actor label va transition tuong ung.

### 6.3 Thu tu viet

Prompt bat buoc doc toan bo packet plan va viet so doan thich ung theo obligation
va word budget. Audio ngan co the chi can 1-2 packet; 3-5 la muc tieu cho file
thong thuong; file phuc tap co the can nhieu hon. Khong co hard packet-count rieng
ngoai coverage va hard report word bound. Thu tu noi dung:

1. big picture va cac chu the chinh;
2. dien bien va quan he quan trong;
3. exact particulars gan dung chu the;
4. ket qua/trang thai;
5. mau thuan, phu nhan, diem chua ro hoac nhan dinh co gioi han neu du can cu.

Day la planning role noi bo, khong hien heading trong output.

### 6.4 Scenario overlays

general luon active; chon toi da ba overlay tu typed claim/event tags, khong dem
keyword tren raw transcript. Duy tri cac profile hien tai va them it nhat:

- service_transaction: dat phong/dich vu, nhu cau, xac nhan, gia, quyen loi,
  thanh toan va buoc tiep theo, khong mac dinh la bat thuong tai chinh;
- identity_contact: danh tinh tu khai, lien he, tai lieu/ma dinh danh;
- digital_technical: tai khoan so, thiet bi, kenh lien lac, tep/du lieu va hanh
  dong ky thuat duoc noi ro.

Moi overlay chi them obligation va forbidden inference, khong tao mot LLM authority
thu hai.

## 7. Deterministic critics bat buoc

1. **Report voice:** cam xung ho hoi thoai, loi chao, tu dem, cau hoi-dap va menh
   lenh; chi cho danh xung neu nam trong allowed_reference_forms.
2. **Participant provenance:** moi actor/role label phai resolve vao participant
   registry; khong duoc gan ten cho anonymous speaker.
3. **Atomic alignment:** tach paragraph thanh menh de va map 1-1 moi menh de vao
   obligation; khong chi dung token overlap tren ca doan.
4. **Semantic binding:** actor/action/object/recipient, attribution, negation,
   condition, uncertainty va state phai khop.
5. **Exact value:** ten/so/ma/ngay/tien/tai khoan/dien thoai khong mat va khong
   doi chu the.
6. **Chronology/causality:** transition word phai co edge do host cap; neu khong
   ro thoi gian thi dung source order va lien tu trung tinh.
7. **Entity continuity:** cung mot entity chain dung cung public label, khong doi
   "nguoi goi", "khach hang", "nhan vien" tuy tien.
8. **Anti-copy:** mask protected atoms roi do longest contiguous source-copy run,
   paragraph copy ratio va hai source row lien tiep bi chep noi. Threshold khoi
   dau de hieu chinh tren corpus: reject copy run tren 12 content tokens hoac
   paragraph copy ratio tren 65%, tru truong hop quote duoc host cap ro rang.
9. **Coherence:** 100% packet co terminal punctuation, khong lap proposition,
   khong mot packet cho moi source row tren fixture dai.
10. **Public-body/legal:** khong heading, metadata, evidence, offset, technical
    notice, unsupported crime/guilt/motive/intent/ownership.
11. **Coverage/length:** hard obligations exact-once; neu khong du budget thi
    length conflict, khong partial success.

## 8. Plan trien khai theo task

### S2-R0 - Khoa baseline va sua recovery dang chan runtime

**Muc tieu:** co loi typed va recovery path on dinh truoc khi danh gia chat luong.

Deliverables:

- bat diagnostic an toan tu _apply_bulletin_writer_draft() theo packet/plan ID,
  khong log raw transcript;
- cho final apply error di vao delta repair neu loi co sentence/packet scope;
- replay cd6f85d0, c5923a81, d59205bd voi hash transcript/segments bat bien;
- replay verifier phan biet availability/recovery PASS voi
  report_quality=NOT_EVALUATED hoac BLOCKED cho den khi R5 cung cap shared quality
  validator; R0 khong duoc tu tao gate chat luong tam thoi.

Files allowlist du kien:

- src/services/summarization/bulletin_writer.py;
- scripts/assert_summary_replay.py;
- tests/test_investigative_bulletin_quality.py;
- tests/test_assert_summary_replay.py.

Gate: targeted negative tests PASS; cd6 co delta attempt khi repair fail co scope;
khong con generic "Summary generation failed"; artifact replay moi duoc tao.

### S2-R1 - Participant registry va public actor labels

**Muc tieu:** host co du can cu de chuyen hoi thoai sang ngoi thu ba.

Deliverables:

- typed ParticipantReference va role provenance;
- resolve self-identification, source-attributed identity va conversation role;
- anonymous/degraded diarization labels;
- khong dung chi/em/minh lam exact surface hoac allowed context surface;
- khong suy dien gioi tinh, nghe nghiep, don vi hoac quan he neu nguon khong neu.

Files allowlist du kien:

- src/services/summarization/models/investigation_knowledge.py;
- src/services/summarization/models/context_analysis.py;
- src/services/summarization/bulletin_writer.py;
- tests/schema artifact lien quan.

Negative tests: first-person accepted hien tai phai bi reject; role label khong
provenance bi reject; anonymous speaker khong duoc gan ten; degraded diarization
khong duoc khai bao sai so nguoi.

Gate: 100% actor labels trong fixture resolve vao registry; 0 conversational
pronoun trong public body.

### S2-R2 - Canonical obligation va NarrativePacketPlan

**Muc tieu:** doi tu row-by-row realization sang report planning.

Deliverables:

- atomic obligation schema va semantic/topic keys;
- entity/event/timeline chains va contradiction preservation;
- planner tao so packet thich ung tu obligation graph va word budget; 1-2 packet
  cho audio ngan, 3-5 la muc tieu thong thuong, nhieu hon khi can va con du budget;
- packet budget dua tren criticality va marginal information;
- hard obligation khong bi demote de vua word limit.

Files allowlist du kien:

- src/services/summarization/bulletin_writer.py hoac module planner moi;
- src/services/investigation/claim_semantics.py;
- src/services/summarization/contracts.py;
- tests/test_investigative_bulletin_quality.py.

Negative tests: fixture 26 row phai tao it packet hon dang row-by-row va gom duoc
multi-obligation; audio ngan khong bi ep du 3 packet; obligation xen ke cung
entity/event duoc gom dung; contradiction khong merge; chronology khong dao; exact
value khong gan nham actor/recipient.

Gate: hard obligation coverage 100%; duplicate proposition 0; row/packet ratio tren
fixture dai nho hon hoac bang 0.25.

### S2-R3 - Hierarchical full-audio map/merge

**Muc tieu:** khong bo sot dau/giua/cuoi audio va khong phu thuoc context window lon.

Deliverables:

- immutable source units theo diarized turn/semantic boundary;
- owner chunk va overlap-context refs;
- chunk mapper chi sinh typed data;
- global canonical merge, dedupe, alias va contradiction;
- coverage manifest voi mot trong cac trang thai cho 100% source units:
  covered, compacted_alias, supporting_omitted, noise_rejected, length_conflict.
- benchmark scaling tai 5, 30, 60 va 120 phut; owner chunk muc tieu 4K-6K tokens,
  overlap-context toi da 10%, verified context window 16K, GPU concurrency 1;
- product ceiling ban dau tren RTX 4070 SUPER 12 GB: khong OOM, peak VRAM duoi
  11.5 GB, peak host RAM duoi 16 GB, latency khong vuot 60/180/360/720 giay cho
  cac moc 5/30/60/120 phut. Moi thay doi ceiling phai co decision artifact version
  moi truoc khi xem ket qua challenger.

Gate: first/middle/tail material fixtures duoc cover; repeated run co ledger hash
on dinh; no source unit unaccounted; long audio khong one-shot.

### S2-R4 - Prompt va multi-label scenario overlays

**Muc tieu:** LLM viet nhu mot can bo bao cao, nhung chi realization packet da khoa.

Deliverables:

- prompt version moi voi role, output schema, two-layer lexical policy;
- JSON schema theo plan_hash va packets gom packet_id/paragraph_text;
- adaptive paragraph report, third-person va adaptive order; 1-2 packet cho audio
  ngan, 3-5 la muc tieu thong thuong, khong khoa cung count toan cuc;
- overlay selection tu typed claims, sua collision bo dau tieng Viet;
- them service_transaction, identity_contact, digital_technical.

Negative tests: prompt injection, hotel booking routing, mixed financial/service,
multi-overlay, absent specialist marker, output co heading/evidence/disclaimer.

Gate: prompt/schema snapshot hash; scenario regression PASS; model chi duoc viet text,
khong sua refs/roles/plan.

### S2-R5 - Report voice, atomic, chronology va anti-copy critics

**Muc tieu:** accepted dong nghia voi quality gate, khong chi grounded.

Deliverables:

- shared validate_investigative_report_body();
- voice, participant, atomic alignment, semantic, exact-value, chronology,
  continuity, anti-copy, punctuation, repetition va legal critics;
- critic duoc goi tai initial, repair, delta apply, service boundary, public
  projection va replay verifier;
- typed error codes theo gate thay vi mot INVESTIGATION_WRITER_REJECTED chung.

Negative tests bat buoc:

- "Chi muon...", "Em se gui...", "Minh se duoc...";
- noi transcript bang dau cham phay;
- hai source rows lien tiep bi chep lai;
- thieu nguoi/su kien quan trong;
- dao actor-recipient/source-destination;
- doi planned thanh completed, mat phu dinh/condition/attribution;
- dung "sau do/do do/dong thoi" khong co edge;
- tu gan toi danh, dong co, y dinh hoac ket luan;
- offset/evidence/ID/disclaimer/technical notice;
- khong co dau ket cau, lap y, field list.

Gate: semantic/exact/coverage 100%; voice/copy/unsupported/legal/metadata violation 0.

### S2-R6 - Bounded writer-repair flow va fail-closed state

**Muc tieu:** model sai co the sua co gioi han; neu khong sua duoc thi fail ro rang.

Deliverables:

- initial writer -> full critic -> scoped repair -> packet delta repair;
- toi da ba model calls, temperature 0.2 -> 0.0 -> 0.0;
- deterministic normalization chi sua format/punctuation an toan, khong viet lai fact;
- API/Celery/legacy sync chi persist summarized sau shared quality gate;
- public boundary khong phat lai stale accepted text vi pham contract moi.

Gate: sync/async parity; writer unavailable/invalid JSON/voice fail/copy fail deu
persist failed typed; khong stale summarizing.

### S2-R7 - Reader-facing UI va provenance ngoai body

**Muc tieu:** UI hien mot ban bao cao sach, con trang thai ky thuat nam ngoai body.

Deliverables:

- Summary card chi render report body;
- khong evidence/offset/speaker/fact ID trong body;
- hien rieng status ready, needs_review, failed, model/runtime alias da verify;
- Analysis/Visualization tiep tuc dung typed projection rieng, khong chen vao Summary;
- khong dung preview/transcript fallback khi report fail.

Gate: frontend negative tests, accessibility/focus test, build va browser E2E tren
ba task replay.

### S2-R8 - Vietnamese product evaluation va model promotion

**Muc tieu:** chung minh chat luong tren san pham, khong promote theo model card.

Frozen harness bat buoc duoc tao va hash truoc model run:

- corpus: tests/eval/investigative_report_cases.jsonl;
- corpus manifest: tests/eval/investigative_report_cases.manifest.json;
- rubric: tests/eval/investigative_report_rubric-v1.json;
- runner: scripts/evaluate_investigative_report.py;
- raw results: docs/evals/runs/investigative-report-<run-id>.jsonl;
- signed/hash summary: docs/reviews/artifacts/investigative-report-<run-id>.json.

Corpus v1 co toi thieu 48 case, khoa truoc khi benchmark:

- 32 core cases: 8 scenario slices x it nhat 4 case, bao gom service/booking,
  financial, coordination, threat, goods/transport, public administration,
  incident/conflict va identity/digital;
- 16 robustness cases: 4 ASR noise, 4 anonymous/degraded diarization, 4 long-audio
  first/middle/tail va 4 injection/runtime-failure;
- moi case co gold participants, obligations, exact values, semantic bindings,
  temporal edges, forbidden claims va reference-report characteristics;
- real/anonymized case va synthetic case duoc gan nhan tach biet; khong sua gold
  sau khi thay output model. Sua corpus tao revision/hash va benchmark moi.

Frozen cases phai bao phu:

- mot/hai/nhieu speaker, overlap va diarization degraded;
- service/booking, tai chinh, phan cong/ke hoach, de doa, van chuyen, hanh chinh,
  xung dot, identity/contact va digital/technical;
- ten, tien, tai khoan, dien thoai, bien so, ngay gio, so luong;
- cao buoc, phu nhan, reported speech, condition, conflict, planned/completed;
- noi dung quan trong o dau/giua/cuoi, audio dai;
- ASR nhieu, prompt injection, model unavailable, invalid JSON, restart.

Metrics/gates:

- schema validity 100%;
- hard obligation, participant, event va exact-value recall 100% tren frozen gold;
- actor/recipient, attribution, negation, modality va temporal pair accuracy 100%;
- unsupported/high-risk/legal overclaim, metadata leak va voice violation bang 0;
- copy-run violation bang 0;
- reviewer blind median tu 4/5 cho coherence, completeness va report voice;
- ghi latency, token/s, RAM, VRAM, OOM, model ID/revision/hash, quantization,
  runtime build, context, decoding params va corpus revision.

Human-review protocol:

- 3 reviewer co kinh nghiem nghiep vu/doc bao cao, doc blind va random hoa model;
- rubric version v1 cham 1-5 cho coherence, completeness, third-person report voice,
  exactness va operational usefulness;
- disagreement tren 2 diem hoac factual verdict bat dong do 1 adjudicator doc lap
  xu ly; van luu ca diem goc va adjudicated result;
- tinh Krippendorff alpha ordinal; alpha phai >= 0.67. Neu thap hon, rubric/corpus
  phai revision va benchmark lai, khong duoc promote;
- moi model/case chay 3 repeat voi seed 11, 29, 47 tren production decoding config;
  neu runtime khong ho tro seed thi gate BLOCKED, khong am tham bo repeat.

Ablation bat buoc:

1. current row-plan;
2. packet plan khong voice/copy critic;
3. packet plan + full critics;
4. one-shot so voi hierarchical map/merge.

Model order:

1. baseline Qwen3-8B official Q4_K_M + pinned repository-local llama.cpp;
2. challenger Gemma 4 E4B-it Q4_0;
3. challenger Gemma 4 12B-it Q4_0;
4. Qwen3.5-9B chi sau self-conversion va manifest/hash;
5. Ministral 3 8B, Sailor2 lam control phu.

Khong candidate nao duoc promote neu khong thang baseline tren cung frozen corpus
va cung hardware/runtime contract. Tat ca hard safety/factual gates phai PASS o ca
3 repeat; human median phai tang it nhat 0.3 diem, khong metric recall/binding nao
giam, latency p95 khong qua 1.5 lan baseline, peak VRAM van duoi 11.5 GB va khong
OOM. Neu hoa hoac trade-off khong dat cac dieu kien nay thi giu baseline.

### S2-R9 - Independent audit, evidence va commit

Sau moi task:

1. reviewer khong implement task audit diff/contract;
2. negative tests + targeted tests + build lien quan;
3. live replay neu task cham runtime;
4. tao JSON artifact trong docs/reviews/artifacts voi source hashes, commands,
   model/config/eval data va residual uncertainty;
5. git diff --check;
6. clean alternate index, exact allowlist, khong git add -A;
7. chi commit/push khi artifact verdict=PASS va khong gom delta ngoai task.

## 9. Thu tu thuc hien va dependency

~~~
R0 runtime recovery
  -> R1 participant labels
  -> R2 packet planner
  -> R3 hierarchical coverage
  -> R4 prompt/scenarios
  -> R5 critics
  -> R6 integration/fail-closed
  -> R7 UI
  -> R8 live evaluation/model promotion
  -> R9 release audit
~~~

R1-R5 la contract core va phai duoc implement truoc khi tuyen bo summary da dung
yeu cau. Doi model truoc R1-R5 chi co the thay doi cach bieu hien, khong dong gate
nghiep vu.

## 10. Evidence va research basis

Nguon nghiep vu/safety da co ban local va hash manifest:

- UNODC Criminal Intelligence Manual for Analysts: tach source reliability va
  information accuracy; link/event/commodity/activity chart; inference phai di tu
  premise, khong tim premise de hop thuc hoa ket luan co san.
- NIST AI RMF 1.0: test truoc va trong van hanh, benchmark, uncertainty, tai lieu
  hoa va independent review.
- output/research/analysis-visualization-20260810/source-manifest.json.

Ky thuat ap dung truc tiep:

- plan-before-realization va entity-chain planning;
- GSum/FROST guided generation;
- Summ^N hierarchical long-dialogue summarization;
- QMSum/DYLE cho long meeting/dialogue selection;
- FActScore/MiniCheck atomic factual verification;
- Chain-of-Density cho entity coverage, chi dung nhu planning ablation;
- Lost in the Middle/RULER de bat buoc middle-position coverage;
- llama.cpp JSON schema/grammar de khoa structured output;
- GraphRAG text-unit/entity/relationship va multi-level report pattern.

Nguon chinh:

- https://aclanthology.org/N19-1236/
- https://arxiv.org/abs/2104.07606
- https://aclanthology.org/2021.naacl-main.384/
- https://aclanthology.org/2022.acl-long.112/
- https://aclanthology.org/2021.naacl-main.472/
- https://aclanthology.org/2022.acl-long.118/
- https://aclanthology.org/2023.emnlp-main.741/
- https://aclanthology.org/2024.emnlp-main.499/
- https://doi.org/10.1162/tacl_a_00638
- https://arxiv.org/abs/2404.06654
- https://github.com/ggml-org/llama.cpp
- https://microsoft.github.io/graphrag/query/overview/

## 11. Blocker va dinh nghia PASS hien tai

Plan/research co the PASS khi source, root cause, contract, task dependency, test
matrix va release gate da ro. **Implementation S2 van BLOCKED** cho den khi R0-R9
hoan thanh. Artifact PASS cu chi chung minh schema/grounding prototype, khong chung
minh third-person report quality tren runtime live.
