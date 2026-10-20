# ProjectA_1 — Sales Forecasting App

ระบบพยากรณ์ยอดขายสำหรับเจ้าของธุรกิจ โดยใช้ Machine Learning เพื่อช่วยติดตามแนวโน้มยอดขายระดับบริษัท สาขา หมวดหมู่ และ SKU

## จุดเด่น

- Dashboard ภาษาไทยเป็นหลัก พร้อมคำภาษาอังกฤษที่จำเป็น และสลับ **Light / Dark mode**
- มุมมองยอดขายจริงเทียบผลพยากรณ์รายวันล่วงหน้า 7/14/28 วัน พร้อมจำนวนชุดสาขา/SKU/ช่องทางที่นำมาคำนวณ
- เก็บผลพยากรณ์รายวัน 28 วันแยกตามสาขา/SKU/ช่องทางเมื่อเทรน เพื่อเทียบกับยอดจริงที่นำเข้าภายหลังในรายงานรายสัปดาห์/เดือน (แสดงความครอบคลุมของคู่ข้อมูลที่ตรงกัน)
- What-if สำหรับปรับสมมติฐานปริมาณขายและราคา ±50% คำนวณจากผลพยากรณ์เดิม ไม่ใช่การเทรนหรือทำนายใหม่
- เทรน XGBoost แบบ Poisson สำหรับจำนวนขายที่ไม่ติดลบ พร้อม rolling backtest สูงสุด 3 จุดตัดเวลา วัดผลพยากรณ์ต่อเนื่อง 7/14/28 วันด้วย WAPE, MAE และ RMSE เทียบกับ baseline ที่ใช้ยอดขาย 7 วันก่อน
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

### ใช้ PostgreSQL ในเครื่อง

สร้างฐานข้อมูล `projecta1` และบัญชีที่เป็นเจ้าของฐานข้อมูลนั้น (ไม่ใช้ superuser `postgres` เป็นบัญชีของแอป) จากนั้นกำหนด `DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/projecta1` ใน `backend/.env` ซึ่งถูก Git ignore ไว้แล้ว. อย่าใส่รหัสผ่านลงในไฟล์ที่ commit หรือส่งภาพหน้าจอที่แสดงรหัสผ่าน

ถ้าใช้ PostgreSQL ที่ติดตั้งในเครื่องบนพอร์ต 5432 อยู่แล้ว อย่าเปิดฐานข้อมูลของ Docker Compose พร้อมกันบนพอร์ตเดียวกัน; คำสั่งรันแบบ local ด้านล่างใช้ PostgreSQL ในเครื่องโดยตรง

จาก `C:\ProjectA\backend` ให้รัน migration ก่อนเปิด API:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

ค่าเริ่มต้น SQLite ยังคงเปิดได้โดยไม่ต้องตั้งค่า แต่ PostgreSQL จะไม่สร้างตารางอัตโนมัติเมื่อ API เริ่มทำงาน; ทุกครั้งที่ดึงโค้ดที่มี migration ใหม่ ให้รัน `alembic upgrade head` ก่อน. การเปลี่ยน `DATABASE_URL` เพียงอย่างเดียวไม่คัดลอกบัญชีหรือข้อมูลเดิมจาก SQLite ไป PostgreSQL — จะเริ่มฐานข้อมูลใหม่หรือใช้สคริปต์คัดลอกด้านล่างก็ได้

หากมีข้อมูลอยู่ใน `backend/projecta1.db` และฐาน PostgreSQL **ยังว่าง** หลัง migration สามารถตรวจจำนวนแถวแล้วคัดลอกด้วยคำสั่งด้านล่างได้ สคริปต์จะไม่เขียนทับฐานที่มีข้อมูล, คัดลอกแบบ transaction เดียว และไม่แก้ไฟล์ SQLite เดิมหรือคัดลอก session ที่ล็อกอินอยู่ (ต้องเข้าสู่ระบบใหม่)

```powershell
.\.venv\Scripts\python.exe scripts\copy_sqlite_to_postgres.py
.\.venv\Scripts\python.exe scripts\copy_sqlite_to_postgres.py --execute
```

การติดตั้ง `npm install`, `python -m venv` และ `pip install` ต้องทำครั้งแรกหรือเมื่อ dependencies เปลี่ยนเท่านั้น. ครั้งถัดไปเริ่มที่ `npm run dev` และ Activate/`uvicorn` ได้เลย หากเว็บเปิดได้แต่กดแล้วไม่เกิดผล ให้ตรวจว่า API ยังทำงานอยู่ที่ [http://localhost:8000/health](http://localhost:8000/health)

## API ที่พร้อมใช้

- `GET /health` — ตรวจสถานะ API
- `POST /api/v1/auth/register`, `/login`, `/logout` และ `GET /me` — บัญชีและ session
- `GET /api/v1/summary` — สรุปข้อมูลจริงขององค์กร
- `GET /api/v1/forecast?days=28` — ผลพยากรณ์จากโมเดลที่เทรนแล้ว
- `GET /api/v1/reports/forecast-vs-actual?grain=week|month` — รายงาน snapshot เทียบยอดจริง โดยเลือก `run_id` และตัวกรองสาขา/SKU/หมวดหมู่/ช่องทางได้
- `POST /api/v1/uploads/validate` — ตรวจไฟล์ก่อนนำเข้า
- `POST /api/v1/uploads/import` — บันทึกข้อมูลขายลงฐานข้อมูลที่ตั้งค่าไว้
- `POST /api/v1/models/train` — เทรนโมเดล XGBoost
- `backend/scripts/benchmark_models.py` — เปรียบเทียบโมเดลกับ baseline แบบอ่านอย่างเดียว โดยกัน 28 วันท้ายไว้เป็น holdout (ต้องตั้ง `backend/.env` ให้ชี้ PostgreSQL)
- `backend/scripts/benchmark_olist.py` — ประเมินกับข้อมูล Olist แหล่งใหม่แบบอ่าน CSV อย่างเดียว ไม่ใช้ฐานข้อมูลแอป; ดูวิธีรัน ผล และข้อจำกัดใน [รายงาน Olist](reports/olist-independent-benchmark.md)
- `GET /api/v1/export` — ดาวน์โหลดข้อมูลขาย CSV

ไฟล์โมเดลที่เทรนแล้วอยู่ใน `backend/artifacts/` และผูกด้วยรหัสสุ่มที่บันทึกไว้ในผลการเทรนของฐานข้อมูลนั้นโดยเฉพาะ การสลับ SQLite ↔ PostgreSQL หรือการสร้างองค์กรใหม่ที่ได้เลข ID เดิมจะไม่หยิบโมเดลจากอีกฐานข้อมูลมาใช้ หากฐานข้อมูลไม่มีรายการเทรนที่ตรงกับไฟล์โมเดล ระบบจะแสดงให้เทรนใหม่ การนำเข้าข้อมูลชุดใหม่จะยกเลิกผลการเทรนเดิมขององค์กรนั้น

ตาราง `forecast_snapshots` เก็บผลพยากรณ์ ณ วันที่เทรนไว้ แม้จะนำเข้าชุดข้อมูลใหม่แล้วก็ตาม (แต่ไฟล์โมเดลเดิมถูกลบและต้องเทรนใหม่) รายงานเทียบ Actual เฉพาะวัน/สาขา/SKU/ช่องทางที่พบข้อมูลจริง และแสดงจำนวนคู่ที่เทียบได้; วันขาดข้อมูลไม่ใช่ยอดขายศูนย์. `forecast_total` คือผลพยากรณ์ครบช่วง ส่วน `forecast_matched` คือเฉพาะคู่ที่ใช้คำนวณส่วนต่าง. ผลจากก่อนเพิ่มฟีเจอร์นี้จะไม่มี snapshot ต้องเทรนอีกครั้ง

## ความปลอดภัยก่อน deploy

- ใช้ HTTPS เสมอ และกำหนด CORS เฉพาะ Vercel URL จริง
- เก็บ DATABASE_URL ใน environment variables และตั้ง `COOKIE_SECURE=true` บน HTTPS
- ก่อนเปิดให้ผู้ใช้สาธารณะ ควรเพิ่ม rate limiting, email verification, password reset และ audit log; โครงสร้างฐานข้อมูลใช้ Alembic migrations แล้ว แต่ต้องรัน migration ทุกครั้งก่อนเริ่ม API หลังอัปเดตโค้ด
- ปัจจุบันการอัปโหลดใหม่จะแทนที่ข้อมูลชุดก่อนขององค์กรนั้นและทำให้ต้องเทรนโมเดลใหม่ แต่ยังเก็บ snapshot การพยากรณ์เดิมเพื่อประเมินย้อนหลัง

## Dataset สำหรับเดโม

แนะนำ [M5 Forecasting Accuracy](https://www.kaggle.com/competitions/m5-forecasting-accuracy/data): มีข้อมูลยอดขายรายวันระดับสินค้าและสาขา รวมถึงราคา ปฏิทิน event และ promotion เหมาะกับโจทย์พยากรณ์แบบ hierarchy. ข้อมูลชุดนี้ไม่มีช่องทางขายโดยตรง ดังนั้น `channel` จะเป็น optional ในระบบ

### ทดสอบครบวงจรด้วยข้อมูลธุรกรรมจริง

จาก `C:\ProjectA\backend` รัน:

```powershell
.\.venv\Scripts\python.exe scripts\real_data_e2e.py --browser
```

เอา `--browser` ออกได้หากต้องการทดสอบเฉพาะ API; เพิ่ม `--source-zip <path>` หากดาวน์โหลดไฟล์ไว้แล้ว โหมด `--browser` ต้องมี Edge และ `npm install` แล้ว; หากมี `npm run dev` เปิดอยู่ ให้หยุดด้วย `Ctrl+C` ก่อนเพื่อไม่ให้ Next.js สองตัวใช้ build cache เดียวกัน สคริปต์ใช้ [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online%2Bretail) ซึ่งเป็นยอดขายจริงปี 2010–2011 และดาวน์โหลดไฟล์ดิบไว้ในโฟลเดอร์ทดสอบชั่วคราวที่ลบเมื่อจบรอบ ไม่ส่ง `CustomerID` หรือข้อความอิสระเข้า API. ระบบจะสมัครบัญชีทดสอบ นำเข้าประวัติ 6 SKU เทรนและพยากรณ์ 28 วัน จากนั้นนำยอดจริงที่กันไว้เข้าระบบเพื่อวัดผลพยากรณ์ที่บันทึกไว้ โหมดเริ่มต้นใช้ SQLite และโมเดลในโฟลเดอร์ชั่วคราว ไม่เปลี่ยนข้อมูลของบัญชีที่คุณใช้งานอยู่

เมื่อต้องการทดสอบบน PostgreSQL ให้สร้างฐานข้อมูลแยกชื่อ `projecta1_test` โดยให้บัญชีแอปเป็นเจ้าของ แล้วเพิ่ม `--postgres` ในคำสั่งข้างต้น สคริปต์จะนำ URL จาก `backend/.env` มาเปลี่ยนชื่อฐานข้อมูลเป็น `<ชื่อเดิม>_test`, รัน Alembic migration และทำ E2E ในฐานข้อมูลทดสอบเท่านั้น; โมเดลยังอยู่ในโฟลเดอร์ชั่วคราว บัญชีทดสอบจะยังอยู่ใน `projecta1_test` เพื่อให้ตรวจผลได้ และไม่แตะ `projecta1`

ข้อมูลต้นทางเป็น GBP; เพื่อเข้ากับหน้าจอที่แสดงบาท สคริปต์คูณราคาด้วยอัตราสมมติ **40 THB/GBP เพื่อเดโมเท่านั้น** ไม่ใช่อัตราแลกเปลี่ยนในอดีต วันไม่มีธุรกรรมถูกระบุเป็นยอดขาย 0 และใช้ราคาขายล่าสุดที่สังเกตได้; ยอดคืน/ยกเลิกถูกตัดออก การทดลองนี้วัดความสามารถของระบบกับร้านออนไลน์เดียว ไม่ได้พิสูจน์ความแม่นยำสำหรับธุรกิจไทยทุกประเภท ดูผลและข้อจำกัดใน [รายงานทดสอบ](reports/uci-online-retail-e2e.md)
