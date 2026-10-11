# ProjectA_1 — Sales Forecasting App

ระบบพยากรณ์ยอดขายสำหรับเจ้าของธุรกิจ โดยใช้ Machine Learning เพื่อช่วยติดตามแนวโน้มยอดขายระดับบริษัท สาขา หมวดหมู่ และ SKU

## จุดเด่น

- Dashboard ภาษาไทยเป็นหลัก พร้อมคำภาษาอังกฤษที่จำเป็น และสลับ **Light / Dark mode**
- มุมมองยอดขายจริงเทียบผลพยากรณ์รายวันล่วงหน้า 7/14/28 วัน พร้อมจำนวนชุดสาขา/SKU/ช่องทางที่นำมาคำนวณ
- เทรน XGBoost พร้อม rolling backtest สูงสุด 3 จุดตัดเวลา วัดผลพยากรณ์ต่อเนื่อง 7/14/28 วันด้วย WAPE, MAE และ RMSE เทียบกับ baseline ที่ใช้ยอดขาย 7 วันก่อน
- นำเข้า CSV/XLSX พร้อมตรวจคอลัมน์สำคัญ, วันที่, ยอดขายติดลบ และป้องกัน PII เช่น อีเมล โทรศัพท์ หรือที่อยู่
- รองรับข้อมูลตามลำดับชั้น: Company → Store → Category → SKU และรองรับ `channel` เมื่อไฟล์ต้นทางมี
- สมัครบัญชีเจ้าของธุรกิจ, เข้าสู่ระบบและออกจากระบบ; ข้อมูลแต่ละองค์กรแยกกัน
- เมนูภาพรวม, การพยากรณ์, นำเข้าข้อมูล, ประสิทธิภาพโมเดล และตั้งค่าใช้งานได้จริง

## Tech stack

| ส่วน | เทคโนโลยี |
| --- | --- |
| Web | Next.js App Router, TypeScript, Recharts |
| ML API | FastAPI, pandas, scikit-learn, XGBoost |
| Database | PostgreSQL หรือ SQLite สำหรับทดลอง / SQLAlchemy |
| Local runtime | SQLite สำหรับทดลอง หรือ Docker Compose + PostgreSQL |

## รูปแบบไฟล์ขาย

คอลัมน์จำเป็น: `date`, `store_id`, `sku_id`, `quantity_sold`, `unit_price`

คอลัมน์ที่แนะนำ: `store_name`, `sku_name`, `category`, `channel`, `discount`, `promotion_flag`, `holiday_flag`

ตัวอย่าง:

```csv
date,store_id,store_name,sku_id,sku_name,category,channel,quantity_sold,unit_price,promotion_flag
2026-01-01,BKK01,Bangkok Central,FD001,Coffee Beans,Food,in_store,27,189,0
2026-01-02,BKK01,Bangkok Central,FD001,Coffee Beans,Food,in_store,33,189,1
```

ห้ามใส่ข้อมูลระบุตัวบุคคล เช่น `email`, `phone`, `address`, `customer_name` ระบบจะปฏิเสธไฟล์ดังกล่าวโดยตั้งใจ ไฟล์ต้องครอบคลุมอย่างน้อย 90 วันที่แตกต่างกัน และขนาดไม่เกิน 20 MB. ทุกแถวต้องมี `unit_price` เพราะหน้าจอแสดงมูลค่าเป็นบาท (ก่อนหัก `discount`). วันที่ไม่มีแถวข้อมูลถือว่าไม่ทราบยอดขาย ไม่ใช่ยอดขาย 0; หากขายได้ 0 ให้ใส่แถว `quantity_sold=0` โดยตรง

โมเดลแยกอนุกรมรายวันตามสาขา/SKU/ช่องทาง และใช้เฉพาะวันที่มีประวัติต่อเนื่องครบสำหรับ lag 28 วัน การประเมินย้อนหลังใช้ข้อมูลก่อนจุดตัดเวลาเท่านั้น แล้วจำลองพยากรณ์ต่อเนื่องโดยไม่แอบใช้ยอดขายจริงระหว่างทาง; เทรนโมเดลสุดท้ายด้วยข้อมูลทั้งหมดหลังประเมิน ผล WAPE รายสาขาและ SKU แสดงเฉพาะกลุ่มที่มีข้อมูลทดสอบครบ และจำนวนรอบ backtest อาจน้อยกว่า 3 หากข้อมูลไม่พอ

## รันด้วย Docker

1. คัดลอก `.env.example` เป็น `.env` และเปลี่ยนรหัสผ่านฐานข้อมูล
2. รัน `docker compose up --build`
3. เปิด `http://localhost:3000` และ API docs ที่ `http://localhost:8000/docs` แล้วสร้างบัญชี

## รันแยกในเครื่อง (Windows PowerShell)

เปิด PowerShell สองหน้าต่างที่ `C:\ProjectA`:

Web:

```powershell
cd C:\ProjectA
npm install
npm run dev
```

API (แนะนำ Python 3.12):

```powershell
cd C:\ProjectA\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

เปิด [http://localhost:3000](http://localhost:3000) แล้วกด **สร้างบัญชี**. ค่าเริ่มต้น API ใช้ SQLite ใน `backend/projecta1.db` เพื่อทดลองได้ทันที. หากเคยเปิด server เดิม ให้กด `Ctrl+C` ที่หน้าต่างเดิมก่อนรันใหม่

การติดตั้ง `npm install`, `python -m venv` และ `pip install` ต้องทำครั้งแรกหรือเมื่อ dependencies เปลี่ยนเท่านั้น. ครั้งถัดไปเริ่มที่ `npm run dev` และ Activate/`uvicorn` ได้เลย หากเว็บเปิดได้แต่กดแล้วไม่เกิดผล ให้ตรวจว่า API ยังทำงานอยู่ที่ [http://localhost:8000/health](http://localhost:8000/health)

## API ที่พร้อมใช้

- `GET /health` — ตรวจสถานะ API
- `POST /api/v1/auth/register`, `/login`, `/logout` และ `GET /me` — บัญชีและ session
- `GET /api/v1/summary` — สรุปข้อมูลจริงขององค์กร
- `GET /api/v1/forecast?days=28` — ผลพยากรณ์จากโมเดลที่เทรนแล้ว
- `POST /api/v1/uploads/validate` — ตรวจไฟล์ก่อนนำเข้า
- `POST /api/v1/uploads/import` — บันทึกข้อมูลขายลงฐานข้อมูลที่ตั้งค่าไว้
- `POST /api/v1/models/train` — เทรนโมเดล XGBoost
- `GET /api/v1/export` — ดาวน์โหลดข้อมูลขาย CSV

ไฟล์โมเดลที่เทรนแล้วอยู่ใน `backend/artifacts/` และผูกด้วยรหัสสุ่มที่บันทึกไว้ในผลการเทรนของฐานข้อมูลนั้นโดยเฉพาะ การสลับ SQLite ↔ PostgreSQL หรือการสร้างองค์กรใหม่ที่ได้เลข ID เดิมจะไม่หยิบโมเดลจากอีกฐานข้อมูลมาใช้ หากฐานข้อมูลไม่มีรายการเทรนที่ตรงกับไฟล์โมเดล ระบบจะแสดงให้เทรนใหม่ การนำเข้าข้อมูลชุดใหม่จะยกเลิกผลการเทรนเดิมขององค์กรนั้น

## ความปลอดภัยก่อน deploy

- ใช้ HTTPS เสมอ และกำหนด CORS เฉพาะ Vercel URL จริง
- เก็บ DATABASE_URL ใน environment variables และตั้ง `COOKIE_SECURE=true` บน HTTPS
- ก่อนเปิดให้ผู้ใช้สาธารณะ ควรเพิ่ม rate limiting, email verification, password reset, audit log และ database migrations
- ปัจจุบันการอัปโหลดใหม่จะแทนที่ข้อมูลชุดก่อนขององค์กรนั้นและทำให้ต้องเทรนโมเดลใหม่

## Dataset สำหรับเดโม

แนะนำ [M5 Forecasting Accuracy](https://www.kaggle.com/competitions/m5-forecasting-accuracy/data): มีข้อมูลยอดขายรายวันระดับสินค้าและสาขา รวมถึงราคา ปฏิทิน event และ promotion เหมาะกับโจทย์พยากรณ์แบบ hierarchy. ข้อมูลชุดนี้ไม่มีช่องทางขายโดยตรง ดังนั้น `channel` จะเป็น optional ในระบบ
