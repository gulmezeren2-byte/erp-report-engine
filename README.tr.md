# erp-report-engine

> Pazartesi toplantısının rakamları zaten ERP'nizin veritabanında duruyor. Peki raporu hâlâ kim yazıyor?

**ERP'nizin arkasındaki SQL veritabanı için salt-okunur, kendini doğrulayan bir veri katmanı — hem haftalık raporlar *hem de* AI ajanları için korumalı bir MCP sunucusu. Her sorgu kanıtlanabilir şekilde salt-okunur: 28 saldırıya karşı ölçülmüş, düzyazıda vaat edilmemiş.**

[![CI](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/gulmezeren2-byte/erp-report-engine/blob/main/requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇬🇧 English: [README.md](README.md)

Zamanlanmış tek bir `run` komutu **9 denetlenmiş SELECT** çalıştırır ve kendi kendine yeten bir HTML rapor üretir: 8 haftalık taban çizgisine karşı dört KPI, sürücüsü isimlendirilmiş bulgular, veri kalitesi kapısı ve kaynakla mutabakatı yapılmış satır sayıları. BI lisansı yok, ERP sunucusuna kurulan ajan yok ve **yazma yok — dört katmanda zorlanır (sözcüksel, ayrıştırma-ağacı, yan etkili fonksiyon bekçisi ve salt-okunur oturum), dokümanda vaat edilerek değil**.

![Motorun ürettiği haftalık rapor (demo veritabanından)](assets/erp_report_preview.png)

*Yukarıdaki rapor, pakete dahil demo veritabanına karşı tek komutla üretildi — içine bilerek ekilmiş üç veri kalitesi sorunu dahil; üçünü de kapı yakaladı.*

**Aynı korumalı motor AI ajanlarıyla da konuşur.** `erp-report-engine mcp`, ERP'yi bir ajana *kanonik varlıklar* üzerinden açar (`orders`, asla `LG_001_01_ORFICHE`) — aynı salt-okunur bekçinin arkasında. Bu, MCP ekosisteminin sürekli yanlış yaptığı katman: referans PostgreSQL MCP sunucusunun salt-okunur modu `COMMIT; DROP SCHEMA public CASCADE;` ile aşıldı ve [arşivlendi](https://github.com/modelcontextprotocol/servers-archived/tree/HEAD/src/postgres); Supabase'in MCP'si ders kitabı ["lethal trifecta"](https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/) vakası oldu. Burada bekçi ifadenin **çağırdığı fonksiyonları** denetler, sadece şeklini değil — ve sıfatın sözüne güvenmek zorunda değilsiniz:

**▶ [28 saldırılık güven benchmark'ını çalıştır](https://gulmezeren2-byte.github.io/erp-report-engine/trust.html)** · **[bekçiyi tarayıcında kendin kır](https://gulmezeren2-byte.github.io/erp-report-engine/playground.html)** (gerçek `guard.py`, Pyodide ile, hiçbir yere bir şey gitmez).

[![Salt-okunur bekçi, tarayıcı oyun alanında: bir sunucu-dosyası okuması ve meşhur COMMIT; DROP Postgres bypass'ı reddediliyor, gerçek analitik serbest — gerçek guard.py Pyodide ile çalışıyor](https://raw.githubusercontent.com/gulmezeren2-byte/erp-report-engine/main/docs/assets/playground-demo.gif)](https://gulmezeren2-byte.github.io/erp-report-engine/playground.html)

*Testlerin çalıştırdığı `guard.py`'nin ta kendisi, tarayıcıda: bir dosya okuması ve salt-okunur-transaction kaçışı reddediliyor, gerçek bir agregasyon serbest. [Kendi saldırını yapıştır →](https://gulmezeren2-byte.github.io/erp-report-engine/playground.html)*

## 60 saniyede demo (ERP gerekmez)

```bash
# kurulum (pipx veya uv izole tutar; düz pip de çalışır)
pipx install erp-report-engine          # veya: uv tool install erp-report-engine
# kaynaktan:  pip install .

erp-report-engine init-demo             # demo.db + config.demo.yaml üretir
erp-report-engine run -c config.demo.yaml
```

Her komut `python -m erp_report_engine …` olarak da çalışır. Veritabanı sürücüsünü ekstralarla ekleyin: `pipx install "erp-report-engine[mssql]"` (Logo Tiger / Netsis / Mikro — SQL Server) veya `[postgres]`.

**Docker mu?** `docker build -t erp-report-engine .` sonra `docker run --rm -v "$PWD:/work" erp-report-engine run -c config.demo.yaml`. SQLite ve PostgreSQL kutudan çıkar çıkmaz çalışır; MSSQL için Microsoft'un ODBC sürücüsünü ekleyin ([`Dockerfile`](Dockerfile)). PyPI'a yayın bir GitHub Release uzaklıkta — [`publish.yml`](.github/workflows/publish.yml) [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) ile derleyip yükler (OIDC, saklanan token yok); CI ayrıca wheel'i derleyip her paketlenmiş profilin geldiğini doğrular.

`reports/erp_report_<hafta>.html` dosyasını açın. Motorun bir ciro sıçramasını yakalayıp tek bölgeye atfettiğini, zamanında sevkiyattaki 2 puanlık düşüşü işaretlediğini, 2 haftalık karşılama süresinin altındaki stokları listelediğini — ve yolda bulduğu her mükerrer ve eksi satırı itiraf ettiğini göreceksiniz.

**▶ Canlı örnek raporu görün: [gulmezeren2-byte.github.io/erp-report-engine](https://gulmezeren2-byte.github.io/erp-report-engine/)** (ayrıca [`docs/sample-report.html`](docs/sample-report.html) içinde commit'li).

Ya da premium **Command Center** için `run --dashboard`: koyu, modern, kendi kendine yeten; animasyonlu KPI'lar ve parlayan SPC kontrol-bantlı grafiklerle (**[canlı](https://gulmezeren2-byte.github.io/erp-report-engine/dashboard.html)**):

![Command Center dashboard — SPC kontrol-bantlı grafiklerle koyu glassmorphic bento grid](assets/dashboard_preview.png)

## Tek çalıştırma ne üretir?

| Bölüm | Neyi cevaplar |
|---|---|
| KPI kartları | Ciro, sipariş, zamanında sevkiyat %, düşük stok sayısı — hem geçen haftaya **hem** 8 haftalık taban çizgisine karşı |
| Bulgular | *"Ciro +%6,5 haftalık — ana sürücü: 'Ege' bölgesi (haftanın hareketinin %54'ü, kısmen Marmara tarafından dengelendi (−14.697))"* — sürücü isimli, ters yöne çeken segment de isimli, aksiyon önerili |
| Sinyaller (SPC) | *"Ciro sinyali: 148.291 kontrol limitlerinin ÜSTÜNDE (UCL 143.078 = ortalama 93.168 ± 2,66 × ort. hareketli menzil 18.763, baz n=25 hafta)"* — gerçek bir kayma, haftalık gürültüden ayrılmış, aritmetiği ve örneklem büyüklüğüyle |
| Trendler | 13 tam haftalık ciro ve zamanında sevkiyat, satır-içi SVG (harici varlık yok) |
| Stok dikkat listesi | Karşılama eşiğinin altındaki kalemler, en kötüsü başta |
| Veri kalitesi kapısı | Mükerrer ID, okunamayan tarih, eksi tutar, siparişten önce sevkiyat |
| Kaynak mutabakatı | Çekilen satırlar vs aynı sorgunun bağımsız `COUNT(*)` sonucu — ✓ veya UYUŞMAZLIK |
| SQL denetim izi | Çalıştırılan her ifade; parametreleri, satır sayısı ve süresiyle |
| Çalışma hafızası | *"Ciro 3 haftadır üst üste düşüyor"* — bakış penceresinin ötesinde bağlam |

## Nasıl çalışır?

```mermaid
flowchart LR
    DB[("ERP veritabanı<br/>MSSQL · PostgreSQL · SQLite")]
    PROF["Semantik profil<br/>(YAML sözleşmesi)"]
    GUARD["safe_read<br/>salt-okunur bekçi + denetim"]
    GATE["Veri kalitesi kapısı<br/>+ kaynak mutabakatı"]
    KPI["KPI motoru<br/>ISO haftaları, 8 haftalık taban"]
    INS["İçgörü kuralları<br/>sürücü atfı"]
    HTML["Kendi kendine yeten<br/>HTML rapor"]
    STATE[("state.db<br/>çalışma hafızası")]

    PROF --> GUARD
    DB --> GUARD --> GATE --> KPI --> INS --> HTML
    STATE --- HTML
    GATE --> PBI["Power BI Command Center<br/>(TMDL + PBIR, kod-olarak-yazılmış)"]
```

Bu sistemi taşınabilir kılan katman **semantik profil**: bir ERP'nin şifreli şemasını üç kanonik varlığa — `orders`, `order_lines`, `inventory` — artı **opsiyonel bir `receivables`** varlığına (açık cari, yaşlandırma için; defter erişilebilirse profil eşler, değilse alt katmanlar sorunsuz atlar) eşleyen sürümlü bir YAML sözleşmesi. Motor yalnızca kanonik kolonları görür. Profili değiştirin, rapor aynı kalsın.

## Güvenlik modeli

Bir yazılımı canlı ERP veritabanına doğrultmak bir güven kararıdır. Bu motor konuya böyle yaklaşır — garantiler kodda zorlanır ve testlerle kapsanır:

Salt-okunur **dört katmanda** zorlanır; tek bir hata motoru yazma yapabilir hale getirmez:

| Katman | Nerede zorlanıyor |
|---|---|
| Sözcüksel bekçi | Tek ifade, `SELECT`/`WITH` başı, yorum yok (`--`, `/*`, `#`), yazma/DDL kelimesi yok, yazma-yükselten kilit ipucu yok (`TABLOCKX`, `UPDLOCK`, `XLOCK`). Tarama, metin sabitleri boşaltılarak yapılır — tırnak içindeki bir kelime koddur değil veridir, yani `SELECT 'lütfen bu notu sil'` bir okumadır |
| Ayrıştırma-ağacı bekçisi | `sqlglot` ifadeyi ayrıştırır — ve **ayrıştırabilmek zorundadır**, aksi halde sorgu reddedilir: okuyamadığı bir sorguya kefil olamaz. Tek bir okuma sorgusu olmalı ve ağacında `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`DROP`/`ALTER`/`MERGE`/`EXEC`/`INTO` düğümü bulunmamalı (CTE içine gizlenmiş yazmaları yakalar) |
| Fonksiyon bekçisi | **Masum görünen pek çok `SELECT` aslında okuma değildir.** `pg_read_file`, `lo_export` (dosya *yazar*), `dblink` (dışarı bağlanır), `OPENROWSET`, `LOAD_FILE`, `load_extension` (kod çalıştırır), `query_to_xml` (SQL çalıştırır), `set_config` (4. katmanı kapatır), `SLEEP`/`BENCHMARK` (hizmet reddi) — hepsi isimden reddedilir; hem AST'de hem sözlüksel olarak, çünkü `sqlglot`'un ayrıştıramadığı şey tam da `OPENROWSET` |
| Salt-okunur oturum | PostgreSQL `default_transaction_read_only=on`, SQLite `PRAGMA query_only`, MySQL `SET SESSION TRANSACTION READ ONLY` + `max_execution_time` ve her motorda ifade başına zaman aşımı |

**Ad-hoc SQL — ajan yolu — daha da sıkı.** `query` ve `guarded_query` **katı modda** çalışır: bekçinin *tanımadığı her fonksiyonu* varsayılan olarak reddeder. `sqlglot`'un fonksiyon kaydı allowlist'in kendisidir — taşınabilir analitik fonksiyonları bilir, dosya okuyan veya soket açan hiçbir şeyi bilmez. Paketteki dört profilin dördü de bu modu geçer; hiçbiri tanınmayan fonksiyon çağırmaz.

**Ve bize ait olmayan katman.** MSSQL'de oturum düzeyinde salt-okunur anahtarı yoktur; orada bu katman doğrudan **kullanıcının kendisidir**. Tehlikeli fonksiyon listesi bir denylist'tir ve hiçbir denylist tam kanıtlanamaz — bu yüzden motoru **en az yetkili, salt-okunur bir kullanıcıyla** çalıştırın (MSSQL'de `db_datareader`, PostgreSQL'de yalnız `SELECT` yetkisi; ideali fiziksel bir okuma replikası). Bekçi derinlemesine savunmadır; bekçinin deliği olduğunda tutan katman yetkidir. Deliği oldu da: bu fonksiyon baypasları bu deponun denetlenmesiyle bulundu ve artık [`tests/test_guard.py`](tests/test_guard.py) içinde isimleriyle, diyalekt diyalekt pinlenmiş durumda.

**Sözüme güvenme — ölç.** Bekçi, tekrar üretilebilir bir güven benchmark'ıyla gelir: şekil-odaklı bir bekçinin geçirdiği, dört diyalektte 28 kusursuz-SQL saldırısı — hepsi reddedilir — artı geçmesi gereken meşru okumalar. Sayı düzyazıda iddia edilmez, canlı bir bekçi koşusundan hesaplanır ve CI her commit'te doğrular.

"28/28" ancak *aynı* 28 saldırıya karşı daha zayıf bir bekçinin skoruyla yan yana anlam taşır. Bu yüzden benchmark, aynı korpusu gerçek araçların sıkça kullandığı kestirmelerden geçirir — `SELECT` ile mi başlıyor kontrolü ve yazma-anahtarkelime kara listesi — ve farkı gösterir: bunlar 28'in yalnızca **6**'sını ve **9**'unu reddeder (kara liste, metninde "delete" geçen meşru bir okumayı bile bloklar), bu bekçi ise 28'in hepsini reddeder ve hiçbir okumayı bloklamaz. Bir test, her kestirmeyi kesin olarak geçtiğini sabitler.

```bash
erp-report-engine trust-benchmark
#   bu bekçi                  28/28 saldırı reddedildi · 8/8 okuma serbest
#   SELECT ile başlıyor mu      6/28                   · 8/8   (22'sini geçirir)
#   yazma-anahtarkelime listesi 9/28                   · 7/8   (hem sızdırır hem meşru okumayı kırar)
```

**▶ Sonuçları görün: [güven benchmark'ı](https://gulmezeren2-byte.github.io/erp-report-engine/trust.html)** — her vaka, şiddeti ve gerçekte ne yaptığı. Ya da **[kendin kır](https://gulmezeren2-byte.github.io/erp-report-engine/playground.html)**: tarayıcında çalışan gerçek bekçiye SQL yapıştır (kurulum yok, hiçbir yere bir şey gitmez — Pyodide üzerinden, testlerin çalıştırdığı `guard.py`'nin ta kendisi).

Sadece bekçiyi kendi MCP sunucun ya da DB aracın için mi istiyorsun? Bağımsız paket olarak çıkarıldı: **[`readonly-sql-guard`](https://github.com/gulmezeren2-byte/readonly-sql-guard)** (`pip install readonly-sql-guard`) — tek fonksiyon, yalnız `re` + `sqlglot`.

Daha fazlası: **["düzyazıda salt-okunur" neden salt-okunur değildir](https://gulmezeren2-byte.github.io/erp-report-engine/case-study.html)** (MCP dünyasının iki meşhur veritabanı faciası ve arkasındaki saldırı sınıfı) · **[AI ajanları için salt-okunur veritabanı erişimi, karşılaştırıldı](https://gulmezeren2-byte.github.io/erp-report-engine/comparison.html)** (transaction vs rol vs ifade bekçisi vs semantik katman — her birinin nerede kazandığı konusunda dürüst).

Ayrıca: profil değişkenleri tanımlayıcı-güvenli (`^[A-Za-z0-9_]{1,16}$`, yani `"001; DROP TABLE x"` daha bağlantı kurulmadan hata fırlatır), sırlar asla config dosyasında yaşamaz (yükleyici gömülü kimlik bilgisini her yazımıyla reddeder — `password`, `passwd`, `pwd`, `sslpassword`, ODBC `PWD=` — `url_env` kullanın), çalıştırılan her ifade raporun denetim izinde gönderilir ve satır tavanı (varsayılan 500 bin) her sorguyu sınırlar.

Test paketi bekçiye bir dizi enjeksiyon fırlatır — çoklu ifade, üç sözdiziminde yorum kaçakçılığı, işlem-kontrol eklemeleri (`ROLLBACK`/`COMMIT`), `SELECT INTO`, kilit ipuçları ve bir CTE içine gizlenmiş `DELETE` — ve her birinin hata üretmesini bekler. Bkz. [SECURITY.md](SECURITY.md).

## Kendi ERP'nize bağlayın

1. Bağlantı URL'sini bir ortam değişkenine koyun (asla dosyaya değil):

```bash
# Windows (Sistem Özellikleri → Ortam Değişkenleri, veya:)
setx ERP_DB_URL "mssql+pyodbc://readonly_user:***@SUNUCU/LOGODB?driver=ODBC+Driver+17+for+SQL+Server"
```

2. `config.example.yaml` → `config.yaml` kopyalayın:

```yaml
connection:
  url_env: ERP_DB_URL          # motor URL'yi bu ortam değişkeninden okur
profile: logo_tiger            # pakete gömülü profil adı, ya da kendi YAML'ınızın yolu
profile_vars:
  firm_no: "001"               # yalnız tanımlayıcı-güvenli değerler, doğrulanır
  period_no: "01"
report:
  company_alias: "Şirket"      # yalnız görünen ad — dilerseniz takma ad kullanın
  lookback_weeks: 13
  low_cover_weeks: 2.0
limits:
  row_cap: 500000
  query_timeout_s: 60
```

3. Kuru çalıştırma — `validate` bağlanır, profil sözleşmesini kontrol eder ve sayıları mutabık kılar, **başka hiçbir şeye dokunmaz**:

```bash
python -m erp_report_engine validate -c config.yaml
python -m erp_report_engine run -c config.yaml
```

### Dahil profiller

Profiller paketin içinde gelir ve adla referans verilir (`generic`, `logo_tiger`) — config'inizin yanında bir `profiles/` klasörü bulunması gerekmez.

- **`generic`** — kanonik şema; kendi profilinizi yazmak için de şablon.
- **`logo_tiger`** — MSSQL üzerinde Logo Tiger / GO: `LG_{firma}_{dönem}_ORFICHE` sipariş başlıkları `CLCARD` cari kartlarına bağlı, `ORFLINE` satırları, `STINVTOT` stok toplamları, `TRCODE = 2` satış filtresi ve **opsiyonel cari yaşlandırma** `PAYTRANS`'tan (taksit `TOTAL − PAID`, `MODULENR = 4`). Logo şemaları sürüme göre değişir — profil, güvenmeden önce **kendi** sürümünüzde neyi doğrulamanız gerektiğini not düşer.
- **`netsis`** — MSSQL üzerinde Logo Netsis 3 (şirket-başına-veritabanı): `TBLSIPAMAS`/`TBLSIPATRA` satış siparişleri (`FTIRSIP = '6'`), `TBLCASABIT` cariler, `TBLSTOKPH` stok toplamları ve **opsiyonel cari yaşlandırma** `TBLCAHAR`'dan (açık-kalem vs. yürüyen-bakiye uyarısı satır-içi belirtilmiş — dürüst zayıf nokta). Gerçek üretim entegrasyonlarından saha-eşlemeli; zayıf noktaları (sipariş durumu, teslim tarihleri, cari kapatma yöntemi) kendi kurulumunuzda doğrulamanız için satır-içi işaretli.
- **`mikro`** — MSSQL üzerinde Mikro ERP (Mikro Yazılım, Fly/Jump/V16–V17): `SIPARISLER` (`sip_` önek, satır-düzeyi) satış siparişleri, `CARI_HESAPLAR` cariler, `STOK_HAREKETLERI` eldeki stok (`sth_tip` giriş/çıkış) ve **opsiyonel cari yaşlandırma** `CARI_HESAP_HAREKETLERI`'nden (`cha_vade` vade). Dürüst zayıf noktalar — `sip_tip` satış filtresi, tutarın KDV-dahilliği, siparişte sevk tarihi olmaması ve açık-kalem işareti olmayan saf yürüyen-bakiye cari defteri — kendi sürümünüzde doğrulamanız için satır-içi işaretli.

Logo Tiger, Netsis ve Mikro birlikte Türkiye KOBİ ERP pazarının çoğunu kapsar (hepsi MSSQL). Başka bir ERP için profil yazmak (SAP B1, Odoo, özel sistem) kanonik kolonları üreten **üç SELECT ifadesi** yazmak demektir — ya `profile:` ile gösterdiğiniz bağımsız bir YAML, ya da gömülü gelmesi için `erp_report_engine/profiles/` içine bırakılan bir dosya. Sözleşmenin tamamı bu — ve `validate` doğru yazıp yazmadığınızı anında söyler.

## Otonom hale getirin

Motor tek ve tekrar-güvenli bir komuttur; her zamanlayıcıyla çalışır:

```powershell
# Windows Görev Zamanlayıcı — her Pazartesi 07:00
schtasks /create /tn "erp-haftalik-rapor" /sc weekly /d MON /st 07:00 ^
  /tr "cmd /c cd /d C:\erp-report-engine && python -m erp_report_engine run -c config.yaml"
```

```bash
# cron — her Pazartesi 07:00
0 7 * * 1  cd /opt/erp-report-engine && python -m erp_report_engine run -c config.yaml
```

Her çalışma `state.db` dosyasına eklenir; raporun *"üçüncü ardışık haftalık düşüş"* diyebilmesi buradan gelir — geçmişi ERP'den yeniden sorgulamadan, çalışmalar arası hafıza.

**Çıkış kodları** zamanlayıcının *neden* başarısız olduğuna göre dallanmasını sağlar: `0` başarı · `2` config hatası · `3` veritabanı/bağlantı hatası · `4` sözleşme hatası (profil şeması yanlış veya kaynak sayıları mutabık değil) · `5` `--strict` altında veri kalitesi hatası · `1` beklenmeyen. Makine-okunur sonuç stdout'a gider (`… run -c config.yaml | jq`); loglar stderr'e, istenirse `--log-file run.jsonl` ile bir JSON-satır dosyasına da yazılır. Sayılar mutabık değilse CI hattını düşürmek için `validate --strict` çalıştırın.

**Yalan söyleyemeyen opsiyonel AI özeti.** `run --narrate` bir LLM yönetici özeti ekler — ama *inşa gereği* dürüst: modele **yalnızca** denetlenmiş agregalar verilir (KPI'lar, bulgular, yaşlandırma/yoğunlaşma — asla ham satır değil) ve rapor modelin gördüğü tam veriyi basar, böylece kime ne verildiği doğrulanabilir. Anahtar tanımlı değilse bayrak hiçbir şey yapmaz. Herhangi bir OpenAI-uyumlu uç nokta çalışır, **yerel ve anahtarsız** bir model dahil (Ollama / LM Studio). Çoğu araç halüsinasyon kontrolünü üretimden *sonra* yapıştırır; burada model sızdırabileceği veya abartabileceği hiçbir şeyi zaten görmez.

**Teslimat gömülü.** `run --send` raporu e-postayla gönderir (SMTP), Slack veya Teams'e (Power Automate Workflows) özet atar ve başarı *veya* başarısızlıkta bir [healthchecks.io](https://healthchecks.io) ölü-adam anahtarını pingler — böylece sessiz bir cron fark edilir. Her sır bir ortam değişkeninden gelir; başarısız kanal loglanır, asla ölümcül değildir. Bir `delivery:` bloğunda yapılandırın (bkz. `config.example.yaml`). Tam otomatik bir hat için `power_automate` kanalı Teams'e Adaptive Card atar **ve** HTML raporu SharePoint/OneDrive'a arşivler — içe aktarılabilir akış ve adım adım rehber **[automation/POWER-AUTOMATE.md](automation/POWER-AUTOMATE.md)** içinde. Rapor kendini yazar *ve* kendini gönderir — çoğu BI aracının paralı sattığı özellik.

## Power BI Command Center

Motor, etkileşimli bir Power BI katmanını da besler — ve bu depoda `.pbix` ikilisi yoktur. Ürünün tamamı **kod olarak yazılmış bir PBIP projesi**: semantik model TMDL'de (yıldız şema, açıklamalı 28 DAX ölçüsü — **DAX'ten doğrudan müşteri sparkline'ı ve ürün karşılama çubuğu çizen SVG mikro-grafik ölçüleri** ve bir **cari yaşlandırma** fact + ölçüleri dahil — boşluksuz hafta sırası üstünde çalışan *Time Shift* hesaplama grubu ve alan parametresi), rapor PBIR'de (5 sayfa / 30 görsel, bir betikle kompakt spec'lerden üretiliyor), artı **Microsoft'un resmi tema şemasına karşı doğrulanmış fütüristik koyu tema**.

```bash
python -m erp_report_engine export-powerbi -c config.demo.yaml
# sonra powerbi/ERP Command Center.pbip dosyasını Power BI Desktop'ta açın
```

İmza özellik **Trust sayfası**: kaynak mutabakatı, veri kalitesi kapısı ve SQL denetim izinin tamamı görsel olarak — pano makbuzlarını gösterir. Uyarı eşikleri `insights.py` ile birebir aynı, DAX'te yeniden türetilmiş: tek tanım, iki yüzey. Alan bağlamaları, proje Desktop'ı görmeden önce `pbir-cli` ile TMDL modele karşı doğrulanır. Tam kılavuz: [powerbi/README.tr.md](powerbi/README.tr.md).

## ERP'nize bir ajanla sorun — bekçili MCP sunucusu

Bir yapay zeka ajanının ERP'ye bağlanması kimsenin iyi çözmediği bir güven problemi: mevcut her "ERP MCP" projesi ERP'nin kendi izinlerine güvenen bir REST sarmalayıcısı, her veritabanı MCP'si ajana ham tabloları veriyor. Bu motor başka hiçbir yerde olmayan bileşimi sunuyor — ajanın **kanonik varlıklarla** (`orders`, asla `LG_001_01_ORFICHE` değil) konuştuğu, raporla **aynı üç-katmanlı salt-okunur bekçi ve denetim izi** üzerinden çalışan, her veri sonucunu güvenilmez girdi olarak çerçeveleyen bir [Model Context Protocol](https://modelcontextprotocol.io) sunucusu.

```bash
pipx install "erp-report-engine[mcp]"
erp-report-engine mcp -c config.yaml          # stdio sunucusu
```

Hepsi bekçili yoldan geçen altı araç:

| Araç | Ajanın aldığı |
|---|---|
| `describe_model` | kanonik **semantik katman** — her varlığın granülerliği, her kolonun tipi + *anlamı* (örn. `actual_ship_date` sevkiyata kadar NULL'dır, yani geciken-sevk-edilmemiş sipariş zamanında %'sine sayılmaz) + çalıştırılabilir örnek sorgular. Sadece ad değil anlam — ajanı text-to-SQL'in doğru tarafında tutan şey. Ham ERP tablo adları yok |
| `weekly_report` | tam KPI brifingi — bulgular, veri kalitesi kapısı, mutabakat, SQL denetim izi |
| `reconcile` | çekilen satırlar vs varlık başına bağımsız `COUNT(*)`, güven hükmüyle |
| `aging` | cari yaşlandırma — gün-bazlı kovalarda açık bakiye, gecikme %'si, en çok geciken müşteriler (yalnız agrega) |
| `check_query` | bir SQL ifadesinin bekçiden geçip geçmeyeceği — *çalıştırmadan* |
| `query` | salt-okunur `SELECT`/`WITH` çalıştır, sınırlı ve denetlenmiş; satırlar **güvenilmez veri** olarak döner |

Birinci-parti bir **[ajan skill paketi](skills/)** (`erp-safe-query`, `explain-kpi-move`, `write-erp-profile`) ajana bu grenle *uyumlu* çalışmayı öğretir — sorgudan önce kuru-çalıştır, satır boşaltmak yerine agregala, denetlenmiş sayıları alıntıla, ERP metnini asla komut sanma.

Claude Desktop'ı (veya herhangi bir MCP istemcisini) ona yöneltin:

```json
{ "mcpServers": { "erp": { "command": "erp-report-engine", "args": ["mcp", "-c", "C:\\yol\\config.yaml"] } } }
```

**Ya da Claude Code eklentisi olarak kurun** — korumalı MCP sunucusu, güvenli-sorgu skill'leri ve sıfır-kurulum `/trust-benchmark` + `/erp-schema` komutları, iki satırda:

```
/plugin marketplace add gulmezeren2-byte/erp-report-engine
/plugin install erp-report-engine
```

Sunucu `uvx` ile başlar (elle kurulum yok), projenizden `erp-config.yaml` okur. Skill'ler ve benchmark/şema komutları, siz bir veritabanı bağlamadan **hemen** çalışır. (Ayrıntı: [`.claude-plugin/`](https://github.com/gulmezeren2-byte/erp-report-engine/tree/main/.claude-plugin).)

Ajan **yazamaz**: sözcüksel + AST bekçisi tek okuma sorgusu dışında her şeyi reddeder, oturum salt-okunurdur ve — 2025 MCP veri-sızdırma olaylarının dersiyle — dönen her değer, satırların komut değil veri olduğu notunu taşır. Bildiğimiz kadarıyla, SQL-düzeyinde bekçili ilk ERP MCP sunucusu ve Logo Tiger için ilk. Türkçe veri ve alanlar için MCP sunucularını derleyen [awesome-turkish-mcp](https://github.com/gulmezeren2-byte/awesome-turkish-mcp) listesinde yer alıyor.

## Bu sistem ne YAPMAZ?

Pazarlama değil dürüstlük — canlıya doğrultmadan önce sınırları bilin:

- **Buradaki zamanında sevkiyat OTIF-lite'tır.** Sipariş düzeyinde `sevkiyat ≤ söz verilen` puanlar. Gerçek OTIF, çoğu ERP sipariş tablosunun taşımadığı satır-düzeyi teslim alma verisi ister — bu yüzden rapor "OTIF" değil "zamanında sevkiyat" der ve dipnotta nedenini açıklar.
- **Zamanında sevkiyat yalnızca sevk edilmiş siparişleri puanlar — ve bu yön tehlikelidir.** Geciken ama **hâlâ sevk edilmemiş** bir siparişin `actual_ship_date`'i yoktur; dolayısıyla ne payda ne paydadadır ve metriği hiç cezalandırmaz. Ucuna kadar götürüldüğünde **sevkiyat çökerken zamanında sevkiyat % yükselir**: en kötü siparişler örneklemden sessizce çıkar. Motor bunu bir sipariş tablosunun taşıdığı veriyle düzeltemez; bu yüzden yüzdenin göremediğini sayar — *"Bu hafta N sipariş söz verildi ve sevk edilmedi"* — hem kartta hem ayrı bir bulgu olarak. İkisini birlikte okuyun, yoksa yüzdeyi hiç okumayın.
- **Zamanında sevkiyat hareketleri zayıf örneklemde "çağrılmaz".** İki sevkiyatın 1/2'den 2/2'ye çıkması *gerçekten* "+50 puan"dır ve bunu ciddi bir yüzle raporlamak bir raporun odayı kaybetme şeklidir. Beş puanlanmış sevkiyatın altında hareket gösterilir ama açıkça çağrılmaz.
- **Bulgular işaret fişeğidir, hüküm değil.** "Sürücü: Ege bölgesi, hareketin %111'i" önce nereye bakacağınızı söyler. *Neden* olduğunu söylemez — orası analistin işidir (sizin).
- **Logo Tiger profili saha eşlemesidir, sertifikalı entegrasyon değil.** Logo şemaları sürüme ve yerelleştirmeye göre değişir; profilin saha notları neyi doğrulamanız gerektiğini listeler.
- **İçinde bulunulan yarım hafta asla çizilmez.** Trendler son tamamlanmış ISO haftasında biter; çünkü aslında iki günlük bir haftadan ibaret olan Pazartesi sabahı "çöküşü", panoların güven kaybetme biçimidir.
- **Bu bir haftalık brifingdir, BI platformu değil.** Detaya inme yok, gerçek zamanlı yok, kullanıcı yönetimi yok. Tek iş yapar: Pazartesi raporu kendini yazar, kanıtlarıyla.

## Tasarım kararları

**Bulgular neden LLM değil de kural tabanlı?** Determinizm. Aynı veritabanı durumu her zaman aynı raporu üretir, ERP'nin yanında internetsiz çalışır ve rapordaki her sayı denetim izindeki bir SQL ifadesine kadar sürülebilir. Yeniden türetilemeyecek hiçbir şey üretilmez.

**Neden kendi kendine yeten HTML dosyası?** Sıfır altyapı. Satır-içi SVG grafikler, satır-içi CSS, CDN yok, izleme yok — Outlook önizlemesinde, telefonda, dosya paylaşımında, on yıl sonra da açılır.

**Satır sayıları neden mutabık kılınıyor?** Çünkü "DataFrame'de 494 satır var" ile "kaynak sorgu 494 satır döndürüyor" farklı iddialardır. Başında insan olmayan bir sistem kendi girdisini denetlemek zorundadır — her varlık bağımsız bir `COUNT(*)` ile yeniden sayılır ve uyuşmazlık, kimse bir KPI'a güvenmeden önce kırmızıyla işaretlenir.

## Testler

```bash
pip install pytest && python -m pytest tests/ -v
```

15 test: bekçiye 8 enjeksiyon denemesi, profil sözleşmesi doğrulaması, değişken enjeksiyonu reddi, demo veritabanına karşı uçtan uca tam koşu (bulgular ateşleniyor, ekili kir yakalanıyor, rapor denetim izini taşıyor) — artı Power BI katmanı: ihraç sözleşmesi (benzersiz anahtarlar, boşluksuz hafta sırası) ve PBIP proje bütünlüğü (adlandırma kuralları, görsel çakışma tespiti, tema çözümleme, görsellerdeki her alanın modelde var olması).

## Yol haritası

Tamamlananlar: bekçili MCP sunucusu + birinci-parti ajan skill paketi, opsiyonel **LLM anlatı katmanı** (yalnız-agrega, inşa gereği dürüst), SPC/XmR anomali katmanı, yerel teslimat (SMTP/Slack/Teams/healthchecks) + Power Automate hattı, deklaratif profil kontratları, **üç gerçek Türk-ERP profili** (Logo Tiger, Netsis, Mikro) — her biri opsiyonel **cari yaşlandırma** ile — ciro yoğunlaşma analizi (top-3 payı + HHI), DAX SVG mikro-grafikleri ve şema-doğrulanmış koyu Power BI teması. Sıradaki:

- PyPI'da `pip install erp-report-engine` + bir Docker imajı
- Daha fazla ERP profili (SAP Business One, Odoo, genel ODBC şablonu)
- Yürüyen-bakiye defterleri (Netsis / Mikro) için tam FIFO açık-kalem yaşlandırması — açık-kalem eşleme kurulmadan da yaşlandırma kesin olsun

## Ölçüm dürüstlüğü serisinin parçası

Operasyonunuz hakkında size doğruyu söyleyen araçlar, [Eren Gülmez](https://github.com/gulmezeren2-byte):

- [otif-analytics](https://github.com/gulmezeren2-byte/otif-analytics) — "raporlanan %98"den "OTIF %59"a 5 basamaklı metrik merdiveni
- [forecast-accuracy-lab](https://github.com/gulmezeren2-byte/forecast-accuracy-lab) — WMAPE vs MAPE ve sıfır-düşürmenin tahmininizi neden pohpohladığı
- [opsaudit](https://github.com/gulmezeren2-byte/opsaudit) — çıkarılamayan dürüstlük bloklu operasyon metrikleri CLI'ı
- [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline) — bu motorun CSV ile beslenen küçük kardeşi
- [forecast-autoresearch](https://github.com/gulmezeren2-byte/forecast-autoresearch) — mühürlü holdout'a karşı tahmin iyileştiren bir ajan

## Lisans

[MIT](LICENSE) © Eren Gülmez
