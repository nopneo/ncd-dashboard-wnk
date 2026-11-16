# หมายเหตุโครงตาราง HOSxP ที่แอปใช้ (ตรวจกับฐาน รพ.วังน้ำเขียว 2026-11-11, MariaDB 10.6)

ข้อมูลใน HOSxP เก็บเป็น **tis-620** (ต่อด้วย charset tis620) · `icd10` เก็บแบบไม่มีจุด (`E119`, `I639`) · ทุกอย่างอ่านอย่างเดียว

| เรื่อง | ข้อเท็จจริงที่พบ | ผลต่อแอป |
|---|---|---|
| ทะเบียนคลินิก `clinicmember` | HT 002 = 4,315 คน (ยังติดตาม ~3,914), DM 001 = 3,360 (~2,870), COPD 024 = 150, Asthma 023 = 98 · `discharge` เป็น `NULL`/`N`/`Y` (ยังติดตาม = ไม่ใช่ `Y`) | นิยามสมาชิก: ลงทะเบียนก่อนสิ้นช่วง และไม่ได้จำหน่ายก่อนเริ่มช่วง |
| CKD / Warfarin | `clinic_ckd_member`, `clinic_ckd_member_visit`, `ckd_lab_link` = 0 แถว · `clinicmember` ไม่มีรหัส 021/026 | CKD จาก eGFR+N18 · Warfarin จากการจ่ายยา |
| `clinicmember.lastvisit` | ไม่ถูกอัปเดต (ล่าสุด 2026-07-07) · `next_app_date` ก็เช่นกัน | ขาดนัด/นัดเลยกำหนดคำนวณจาก `ovst` / `oapp` |
| lab | `lab_head`(hn, order_date) + `lab_order`(lab_items_code, lab_order_result varchar) · ผลมีค่าว่าง/ข้อความ | อ่านผ่าน `classify.parse_result` และใช้ค่าล่าสุดที่อ่านได้ |
| รูปแบบผล lab | eGFR ก่อน ธ.ค. 2568 เก็บเป็น `90.58 [Stage 1]` (ตัวเลข+คำอธิบาย) หลังจากนั้นเป็นตัวเลขล้วน · ผล HbA1c/INR/eGFR/LDL/Microalbumin อ่านได้ >99.5% ที่เหลือคือ `No specimen`/ข้อความ | `parse_result` รับคำอธิบาย/หน่วยต่อท้าย |
| รหัส lab | HbA1c 271 · INR 2020 · eGFR 2135 · LDL 270,1956 · Microalbumin 318 | ตั้งผ่าน env |
| ความดัน | `opdscreen`(hn, vstdate, bps, bpd) | กรองค่าผิด (0/999) ด้วย `valid_bp` |
| ยา | `opitemrece`(hn, vn, icode, vstdate) ใหญ่มาก — subquery `hn IN (...)` ช้า ~15 วิ | ดึงตามรหัสยาแล้วตัดกับทะเบียนใน Python |
| รหัสยา | warfarin 1000102/1000104 · statin 1641001,1581202,1000345,1000459,1611005 · ต้านเกล็ดเลือด 1000156,1000376,1000271 · ยาพ่นควบคุม 1000142,1551101,1611104 | ให้เภสัชกรยืนยัน |
| สมรรถภาพปอด | `nondrugitems` 3160033/3160035/3160039 ผ่าน `opitemrece` (ทั้งฐาน 274 ครั้ง/246 คน) | นับย้อนหลังทุกช่วงเวลา |
| ตรวจตา/เท้า DM | `clinic_cormobidity*` ว่าง · `last_cormobidity_screen_vn` มีทุกคน (ใช้ไม่ได้) | แสดง "ไม่มีข้อมูล" |
| Admit / ตาย | `ipt`(an, hn, regdate, dchdate, dchstts) + `iptdiag`(an, icd10) · ตายใน รพ. = `dchstts` 08/09 | ตั้ง `NCD_DCHSTTS_DEAD` ตรวจที่ `/check` |
| ชื่อหน่วยบริการ | `hospcode`(hospcode, name) | ใช้แสดงชื่อ รพ.สต. ในตารางเทียบ HDC |
| บัญชี dev (`hosdb`) | มี ALL PRIVILEGES — `setup_check.py` แจ้ง ✘ | production ต้องใช้บัญชีอ่านอย่างเดียว |

## นิยามที่ใช้ซึ่งทีมคลินิกควรยืนยัน
- **CKD:** eGFR ล่าสุด <60 และมีค่า <60 อีกครั้งห่างกัน ≥90 วัน หรือมีรหัส N18.x ในช่วง · ระยะตาม eGFR ล่าสุด · ไม่มีตาราง KDIGO (หน่วย Microalbumin ยังไม่ยืนยัน)
- **Warfarin:** ผู้ป่วยที่ได้รับยา warfarin ในช่วง · ตัวชี้วัด INR/TTR นับเฉพาะผู้ป่วยกลุ่มนี้
- **CVD:** stroke (I60–I64) / AMI (I21–I22) จากรหัสโรคใน `ovstdiag`/`iptdiag` · รายใหม่ = ไม่มีรหัสเดียวกันใน 3 ปีก่อนหน้า
