# erp-report-engine

> Pazartesi toplantısının rakamları zaten ERP'nizin veritabanında duruyor. Peki raporu hâlâ kim yazıyor?

**ERP'nizin arkasındaki SQL veritabanından otonom haftalık raporlar — mimarisi gereği salt-okunur, her sorgu denetim izinde.**

[![CI](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/gulmezeren2-byte/erp-report-engine/blob/main/requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇬🇧 English: [README.md](README.md)

Zamanlanmış tek bir `run` komutu **6 denetlenmiş SELECT** çalıştırır ve kendi kendine yeten bir HTML rapor üretir: 8 haftalık taban çizgisine karşı dört KPI, sürücüsü isimlendirilmiş bulgular, veri kalitesi kapısı ve kaynakla mutabakatı yapılmış satır sayıları. BI lisansı yok, ERP sunucusuna kurulan ajan yok ve **yazma yok — üç katmanda zorlanır (sözcüksel + ayrıştırma-ağacı bekçisi ve salt-okunur oturum), dokümanda vaat edilerek değil**.

![Motorun ürettiği haftalık rapor (demo veritabanından)](assets/erp_report_preview.png)

*Yukarıdaki rapor, pakete dahil demo veritabanına karşı tek komutla üretildi — içine bilerek ekilmiş üç veri kalitesi sorunu dahil; üçünü de kapı yakaladı.*

## 60 saniyede demo (ERP gerekmez)

```bash
# kurulum (pipx veya uv izole tutar; düz pip de çalışır)
pipx install erp-report-engine          # veya: uv tool install erp-report-engine
# kaynaktan:  pip install .

erp-report-engine init-demo             # demo.db + config.demo.yaml üretir
erp-report-engine run -c config.demo.yaml
```

Her komut `python -m erp_report_engine …` olarak da çalışır. Veritabanı sürücüsünü ekstralarla ekleyin: `pipx install "erp-report-engine[mssql]"` (Logo Tiger / SQL Server) veya `[postgres]`.

`reports/erp_report_<hafta>.html` dosyasını açın. Motorun bir ciro sıçramasını yakalayıp tek bölgeye atfettiğini, zamanında sevkiyattaki 2 puanlık düşüşü işaretlediğini, 2 haftalık karşılama süresinin altındaki stokları listelediğini — ve yolda bulduğu her mükerrer ve eksi satırı itiraf ettiğini göreceksiniz. Hazır üretilmiş bir kopya [`docs/sample-report.html`](docs/sample-report.html) içinde.

## Tek çalıştırma ne üretir?

| Bölüm | Neyi cevaplar |
|---|---|
| KPI kartları | Ciro, sipariş, zamanında sevkiyat %, düşük stok sayısı — hem geçen haftaya **hem** 8 haftalık taban çizgisine karşı |
| Bulgular | *"Ciro +%25,4 — ana sürücü: 'Ege' bölgesi (hareketin %111'i)"* — sürücü isimli, aksiyon önerili |
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

Bu sistemi taşınabilir kılan katman **semantik profil**: bir ERP'nin şifreli şemasını üç kanonik varlığa — `orders`, `order_lines`, `inventory` — eşleyen sürümlü bir YAML sözleşmesi. Motor yalnızca kanonik kolonları görür. Profili değiştirin, rapor aynı kalsın.

## Güvenlik modeli

Bir yazılımı canlı ERP veritabanına doğrultmak bir güven kararıdır. Bu motor konuya böyle yaklaşır — garantiler kodda zorlanır ve testlerle kapsanır:

Salt-okunur **üç katmanda** zorlanır; tek bir hata motoru yazma yapabilir hale getirmez:

| Katman | Nerede zorlanıyor |
|---|---|
| Sözcüksel bekçi | Tek ifade, `SELECT`/`WITH` başı, yorum yok (`--`, `/*`, `#`), yazma/DDL kelimesi yok, yazma-yükselten kilit ipucu yok (`TABLOCKX`, `UPDLOCK`, `XLOCK`) |
| Ayrıştırma-ağacı bekçisi | `sqlglot` ifadeyi ayrıştırır; tek bir okuma sorgusu olmalı ve ağacında `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`DROP`/`ALTER`/`MERGE`/`EXEC`/`INTO` düğümü bulunmamalı (CTE içine gizlenmiş yazmaları yakalar) |
| Salt-okunur oturum | PostgreSQL `default_transaction_read_only=on`, SQLite `PRAGMA query_only` ve son güvence olarak belgelenmiş bir **salt-okunur kullanıcı** (MSSQL'de `db_datareader`) — böylece yazmaya çalışan bir fonksiyon bile veritabanınca reddedilir |

Ayrıca: profil değişkenleri tanımlayıcı-güvenli (`^[A-Za-z0-9_]{1,16}$`, yani `"001; DROP TABLE x"` daha bağlantı kurulmadan hata fırlatır), sırlar asla config dosyasında yaşamaz (yükleyici gömülü kimlik bilgisini reddeder — `url_env` kullanın), çalıştırılan her ifade raporun denetim izinde gönderilir ve satır tavanı (varsayılan 500 bin) her sorguyu sınırlar.

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
- **`logo_tiger`** — MSSQL üzerinde Logo Tiger / GO: `LG_{firma}_{dönem}_ORFICHE` sipariş başlıkları `CLCARD` cari kartlarına bağlı, `ORFLINE` satırları, `STINVTOT` stok toplamları, `TRCODE = 2` satış filtresi. Logo şemaları sürüme göre değişir — profil, güvenmeden önce **kendi** sürümünüzde neyi doğrulamanız gerektiğini not düşer.

Başka bir ERP için profil yazmak (Netsis, SAP B1, Odoo, özel sistem) kanonik kolonları üreten **üç SELECT ifadesi** yazmak demektir — ya `profile:` ile gösterdiğiniz bağımsız bir YAML, ya da gömülü gelmesi için `erp_report_engine/profiles/` içine bırakılan bir dosya. Sözleşmenin tamamı bu — ve `validate` doğru yazıp yazmadığınızı anında söyler.

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

## Power BI Command Center

Motor, etkileşimli bir Power BI katmanını da besler — ve bu depoda `.pbix` ikilisi yoktur. Ürünün tamamı **kod olarak yazılmış bir PBIP projesi**: semantik model TMDL'de (yıldız şema, açıklamalı 20+ DAX ölçüsü, boşluksuz hafta sırası üstünde çalışan *Time Shift* hesaplama grubu, alan parametresi), rapor PBIR'de (4 sayfa / 24 görsel, bir betikle kompakt spec'lerden üretiliyor), artı özel tema.

```bash
python -m erp_report_engine export-powerbi -c config.demo.yaml
# sonra powerbi/ERP Command Center.pbip dosyasını Power BI Desktop'ta açın
```

İmza özellik **Trust sayfası**: kaynak mutabakatı, veri kalitesi kapısı ve SQL denetim izinin tamamı görsel olarak — pano makbuzlarını gösterir. Uyarı eşikleri `insights.py` ile birebir aynı, DAX'te yeniden türetilmiş: tek tanım, iki yüzey. Alan bağlamaları, proje Desktop'ı görmeden önce `pbir-cli` ile TMDL modele karşı doğrulanır. Tam kılavuz: [powerbi/README.tr.md](powerbi/README.tr.md).

## Bu sistem ne YAPMAZ?

Pazarlama değil dürüstlük — canlıya doğrultmadan önce sınırları bilin:

- **Buradaki zamanında sevkiyat OTIF-lite'tır.** Sipariş düzeyinde `sevkiyat ≤ söz verilen` puanlar. Gerçek OTIF, çoğu ERP sipariş tablosunun taşımadığı satır-düzeyi teslim alma verisi ister — bu yüzden rapor "OTIF" değil "zamanında sevkiyat" der ve dipnotta nedenini açıklar.
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

- `profiles/netsis.yaml` — ikinci Türk ERP eşlemesi (`TBLSIPAMAS` ailesi)
- İsteğe bağlı e-posta gönderimi (SMTP yalnız ortam değişkenleriyle, [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline) izinde)
- Anomali katmanı: haftalık kuralların üstüne kontrol limiti ihlalleri
- MCP sunucu sarmalayıcı: aynı salt-okunur bekçi üzerinden ERP'ye soru sormak

## Ölçüm dürüstlüğü serisinin parçası

Operasyonunuz hakkında size doğruyu söyleyen araçlar, [Eren Gülmez](https://github.com/gulmezeren2-byte):

- [otif-analytics](https://github.com/gulmezeren2-byte/otif-analytics) — "raporlanan %98"den "OTIF %59"a 5 basamaklı metrik merdiveni
- [forecast-accuracy-lab](https://github.com/gulmezeren2-byte/forecast-accuracy-lab) — WMAPE vs MAPE ve sıfır-düşürmenin tahmininizi neden pohpohladığı
- [opsaudit](https://github.com/gulmezeren2-byte/opsaudit) — çıkarılamayan dürüstlük bloklu operasyon metrikleri CLI'ı
- [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline) — bu motorun CSV ile beslenen küçük kardeşi
- [forecast-autoresearch](https://github.com/gulmezeren2-byte/forecast-autoresearch) — mühürlü holdout'a karşı tahmin iyileştiren bir ajan

## Lisans

[MIT](LICENSE) © Eren Gülmez
