# SL-AstraCore — ایرادات و وضعیت واقعی

آخرین baseline تأییدشده: commit
`ec7d3b1c7c9835d789037787d07348209d462b0b`

تاریخ بررسی: ۱۴۰۵/۰۹/۰۲

این فایل جایگزین فهرست قدیمی مبتنی بر commit `6040d8e` است. اعداد و
بنچمارک‌های قبلی بدون اجرای مجدد، معیار وضعیت فعلی نیستند.

## موارد پیاده‌سازی‌شده و تأییدشده

| حوزه | وضعیت |
|---|---|
| Unified Runtime / ingestion | مسیر ingestion یکپارچه و checkpoint/manifest پایدار اضافه شده |
| Scanner | ignore rules، شناسه‌های قطعی و incremental state |
| Parser / IR | registry و adapterها با تست چندپلتفرمی |
| Import resolver | حفظ ambiguity برای مقصدهای چندگانه |
| Graph / Storage | گراف و backendهای پایدار با تست‌های تراکنش و دسترسی |
| Context | ranking، retrieval مبتنی بر سورس و سقف بودجهٔ تخمینی |
| Dashboard / API | احراز هویت bearer، محدودسازی مسیر repository و SSE احرازشده |
| Model provider | ورود API Key از داشبورد و اتصال OpenAI-compatible |
| AI review | ساخت context و بررسی پیشنهاد؛ بدون اعمال خودکار فایل |
| Security | bind محلی پیش‌فرض، CodeQL و pip-audit در CI |
| Packaging | ساخت و نصب wheel بیرون از سورس + Docker smoke test |
| Coverage | حداقل اجباری ۹۵٪؛ آخرین اندازه‌گیری ۹۵٫۳٪ |

## گیت‌های آخرین اجرای کامل

[GitHub Actions run #45082074980](https://github.com/Mk18dev/SL-AstraCore/actions/runs/45082074980)

- ۴۹۸ تست موفق در Ubuntu / Python 3.11
- ماتریس Ubuntu، macOS و Windows با Python 3.11 و 3.12: هر ۶ ترکیب سبز
- Ruff و mypy: موفق
- Coverage: ۵۱۷۶ از ۵۴۳۴ خط اجرایی، معادل ۹۵٫۳٪
- Wheel build/install: موفق
- Docker build/smoke: موفق
- CodeQL و dependency audit: موفق
- CI required gate: موفق

## موارد باز

| # | مورد | اولویت | وضعیت / دلیل |
|---|---|---:|---|
| R1 | فعال‌سازی Branch Protection روی main | P0 | تنظیم GitHub است، نه فایل workflow؛ اتصال فعلی فقط خواندن این تنظیمات را می‌دهد. دستور دقیق در docs/BRANCH_PROTECTION.md ثبت شده |
| R2 | رمزنگاری API Key در حالت ذخیره‌شده | P1 | فعلاً plaintext با محدودیت مجوز فایل است؛ باید OS keyring یا راهکار امن و قابل‌اتکا برای هر سه سیستم‌عامل بررسی و پیاده‌سازی شود |
| R3 | TLS و RBAC داخلی | P1 | محصول local-first و تک‌کاربره است؛ برای استقرار چندکاربره باید threat model و احراز هویت جداگانه طراحی شود |
| R4 | Providerهای native و streaming | P2 | فعلاً فقط OpenAI-compatible chat completions پیاده شده |
| R5 | Tokenizer واقعی هر مدل | P2 | بودجه با estimator محافظه‌کارانهٔ UTF-8 محاسبه می‌شود؛ تعداد token دقیق هر provider تضمین نمی‌شود |
| R6 | بنچمارک مجدد performance | P1 | عددهای قبلی مربوط به baseline قدیمی‌اند؛ باید روی commit فعلی و fixture ثابت دوباره اندازه‌گیری شوند |
| R7 | ماتریس صحت parser و graph relation به تفکیک زبان | P1 | وجود adapter به‌تنهایی اثبات Call/Reference graph کامل نیست؛ fixture و ground-truth مستقل لازم است |

## نکات امنیتی مهم

- فایل تنظیمات Provider شامل API Key است و رمزنگاری‌شده نیست؛ آن را commit یا share نکن.
- اجرای مستقیم dashboard روی loopback است؛ Docker داخل container روی همهٔ interfaceها bind می‌کند.
- Docker را بدون reverse proxy دارای TLS و firewall روی شبکهٔ غیرقابل‌اعتماد publish نکن.
- خروجی مدل پیشنهاد است؛ بررسی و اعمال آن دو مرحلهٔ مستقل‌اند.

## مرز استقرار

هیچ deployment یا اتصال Vercel انجام نشده است. این مورد تا اجازهٔ صریح جداگانه خارج از scope باقی می‌ماند.
