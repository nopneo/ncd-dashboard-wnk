"""ค่าตั้งของแอป — รหัสคลินิก/lab/ยา/ICD/เกณฑ์ทั้งหมดอ่านจาก env (คำนำหน้า NCD_)

ค่าเริ่มต้นคือรหัสของ รพ.วังน้ำเขียว · รหัสใน HOSxP ของแต่ละ รพ. ไม่เหมือนกัน
ตรวจที่หน้า /check แล้วตั้ง env ให้ตรงกับข้อมูลของ รพ.ตนเอง
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass


def get(name, default):
    return os.getenv("NCD_" + name, default)


def get_list(name, default):
    """ค่าคั่นด้วยจุลภาค → list (ตัดช่องว่างและค่าว่าง)"""
    return [x.strip() for x in get(name, default).split(",") if x.strip()]


def get_float(name, default):
    try:
        return float(get(name, str(default)))
    except ValueError:
        return float(default)


# --- ทะเบียนคลินิก (clinicmember.clinic) ---
CLINIC_HT = get("CLINIC_HT", "002")
CLINIC_DM = get("CLINIC_DM", "001")
CLINIC_COPD = get("CLINIC_COPD", "024")
CLINIC_ASTHMA = get("CLINIC_ASTHMA", "023")

# --- lab_items_code ---
LAB_HBA1C = int(get("LAB_HBA1C", "271"))
LAB_INR = int(get("LAB_INR", "2020"))
LAB_EGFR = int(get("LAB_EGFR", "2135"))
LAB_LDL = get_list("LAB_LDL", "270,1956")        # ว่าง = ไม่มีข้อมูล (ตรวจที่ /check)
LAB_UACR = get_list("LAB_UACR", "318")           # 318 = Microalbumin
LAB_HB = get_list("LAB_HB", "37")                # 37 = Hemoglobin (HGB) g/dl
LAB_HCT = get_list("LAB_HCT", "38")              # 38 = Hct (CBC) %

# --- ยา (drugitems.icode) ---
DRUG_WARFARIN = get_list("DRUG_WARFARIN", "1000102,1000104")
DRUG_STATIN = get_list("DRUG_STATIN", "1641001,1581202,1000345,1000459,1611005")
DRUG_ANTIPLATELET = get_list("DRUG_ANTIPLATELET", "1000156,1000376,1000271")
# ACEI/ARB: captopril, enalapril 5/20, losartan 50 (รวมรหัสเก่าที่ปิดแล้ว เพื่อข้อมูลย้อนหลัง)
DRUG_ACEI_ARB = get_list("DRUG_ACEI_ARB", "1600801,1000381,1000385,1570601,1000236,1000445")

PROC_SPIROMETRY = get_list("PROC_SPIROMETRY", "3160033,3160035,3160039")      # nondrugitems: Spirometry/PFT
DRUG_INHALER_CONTROLLER = get_list("DRUG_INHALER_CONTROLLER", "1000142,1551101,1611104")   # budesonide, seretide
DCHSTTS_DEAD = get_list("DCHSTTS_DEAD", "08,09")                          # ipt.dchstts = ตาย

# --- เกณฑ์ทางคลินิก / เป้าหมาย ---
INR_LOW = get_float("INR_LOW", 2.0)
INR_HIGH = get_float("INR_HIGH", 3.0)
TTR_TARGET = get_float("TTR_TARGET", 65.0)
HBA1C_TARGET = get_float("HBA1C_TARGET", 7.0)
TARGET_HT_CONTROL = get_float("TARGET_HT_CONTROL", 60.0)    # ร้อยละ
TARGET_DM_CONTROL = get_float("TARGET_DM_CONTROL", 40.0)
# ชะลอไตเสื่อม (หน้า CKD)
CKD_HB_MIN = get_float("CKD_HB_MIN", 10.0)                  # Hb > ค่านี้ (g/dl) ถือว่าผ่าน
CKD_HCT_MIN = get_float("CKD_HCT_MIN", 30.0)                # หรือ Hct > ค่านี้ (%)
CKD_DM_HBA1C_TARGET = get_float("CKD_DM_HBA1C_TARGET", 7.0)  # DM ที่มี CKD 3–4: HbA1c < ค่านี้ = ควบคุมได้
TARGET_CKD_ACEI_ARB = get_float("TARGET_CKD_ACEI_ARB", 60.0)
TARGET_CKD_ANEMIA = get_float("TARGET_CKD_ANEMIA", 60.0)
TARGET_CKD_DM_A1C = get_float("TARGET_CKD_DM_A1C", 40.0)
TARGET_CKD_EGFR = get_float("TARGET_CKD_EGFR", 66.0)        # HDC: eGFR ลดลง <5/ปี (ตัวชี้วัดกระทรวง ≥66%)
READMIT_DAYS = int(get_float("READMIT_DAYS", 28))
# DM remission (ตัวชี้วัด HDC 10.2 · NCDs remission clinic)
PP_REMISSION = get_list("PP_REMISSION", "1I20")             # pp_special_type.pp_special_code ของการเข้าร่วม clinic
#: ยาลดน้ำตาลทุกชนิด (metformin, SU, TZD, insulin RI/NPH/Mixtard รวมที่ใช้ในตึก) — ได้ยาช่วง HbA1c <6.5 = ยังไม่สงบ
DRUG_DM = get_list("DRUG_DM", "1000052,1560201,1000292,1000053,1560202,1000270,1000060,1670004,1000390,1670002,"
                              "1561201,1000232,1000460")
REMISSION_HBA1C = get_float("REMISSION_HBA1C", 6.5)          # HbA1c < ค่านี้
REMISSION_MIN_DAYS = int(get_float("REMISSION_MIN_DAYS", 90))   # ผลตรวจ 2 ครั้งห่างกัน 90–180 วัน
REMISSION_MAX_DAYS = int(get_float("REMISSION_MAX_DAYS", 180))
TARGET_DM_REMISSION = get_float("TARGET_DM_REMISSION", 10.0)    # ร้อยละ A1/B1 (ปีงบ 2568–2569 ≥10%)
# เกณฑ์การเบิก DM Remission (กรอบแนวทางงบบริการ เอกสารแนบ 2) — ต่างจากตัวชี้วัด HDC: ครั้งที่ 1→2 ไม่มีเพดาน (0 = ไม่จำกัด)
CLAIM_LIFESTYLE_DAYS = int(get_float("CLAIM_LIFESTYLE_DAYS", 180))   # ยังไม่เริ่มยา: ลงทะเบียน → HbA1c ครั้งที่ 1
CLAIM_DRUGFREE_DAYS = int(get_float("CLAIM_DRUGFREE_DAYS", 90))      # รักษาด้วยยา: หยุดยา → HbA1c ครั้งที่ 1
CLAIM_PAIR_MIN_DAYS = int(get_float("CLAIM_PAIR_MIN_DAYS", 90))      # ครั้งที่ 1 → 2
CLAIM_PAIR_MAX_DAYS = int(get_float("CLAIM_PAIR_MAX_DAYS", 0))
CLAIM_MAINT_MIN_DAYS = int(get_float("CLAIM_MAINT_MIN_DAYS", 90))    # ครั้งที่ 2 → 3 (maintenance)
CLAIM_MAINT_MAX_DAYS = int(get_float("CLAIM_MAINT_MAX_DAYS", 180))
CLAIM_SUCCESS_BAHT = get_float("CLAIM_SUCCESS_BAHT", 4000)
CLAIM_MAINT_BAHT = get_float("CLAIM_MAINT_BAHT", 2000)
TARGET_FOLLOWUP = get_float("TARGET_FOLLOWUP", 90.0)
TARGET_STATIN = get_float("TARGET_STATIN", 80.0)
TARGET_INR_IN_RANGE = get_float("TARGET_INR_IN_RANGE", 75.0)

# --- รหัสโรค ICD-10 (prefix ไม่มีจุด ตามรูปแบบที่เก็บใน HOSxP — ตรวจที่ /check) ---
ICD_STROKE = get_list("ICD_STROKE", "I60,I61,I62,I63,I64")
ICD_AMI = get_list("ICD_AMI", "I21,I22")
ICD_COPD = get_list("ICD_COPD", "J44")
ICD_ASTHMA = get_list("ICD_ASTHMA", "J45,J46")
ICD_CKD = get_list("ICD_CKD", "N18")
ICD_DIALYSIS = get_list("ICD_DIALYSIS", "Z49,Z992")
ICD_HYPOGLYCEMIA = get_list("ICD_HYPOGLYCEMIA", "E160,E161,E162")
ICD_AKI = get_list("ICD_AKI", "N17")
ICD_BLEEDING = get_list("ICD_BLEEDING", "D683,K920,K921,K922,R040,R041,R042,R048,R049,I61,I62,N02,T455")
