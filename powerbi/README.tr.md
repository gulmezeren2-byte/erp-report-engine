# ERP Command Center — Power BI katmanı

> Aynı motor, aynı dürüstlük — şimdi etkileşimli bir Power BI semantik modeli ve raporu olarak, **tamamı kod olarak yazılmış**.

🇬🇧 English: [README.md](README.md)

Bu depoda `.pbix` ikili dosyası yok. Power BI ürününün tamamı, sürüm-kontrol dostu metin formatlarında bir **PBIP projesi** — semantik model için [TMDL](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview), rapor için [PBIR](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report#pbir-format). Yani her ölçü, her ilişki ve her görsel git diff'inde incelenebilir — motorun geri kalanı gibi.

## Hızlı başlangıç

```bash
# 1. veriyi üret (demo gösterildi; gerçek ERP için kendi config'inizi kullanın)
python -m erp_report_engine init-demo
python -m erp_report_engine export-powerbi -c config.demo.yaml

# 2. projeyi açın (Power BI Desktop, güncel herhangi bir sürüm)
#    çift tıklayın:  powerbi/ERP Command Center.pbip
```

İlk açılışta: **Verileri dönüştür → Parametreleri düzenle → `DataFolder`** parametresini bu deponun `powerbi\data` klasörüne (mutlak yol) ayarlayın, sonra **Yenile**. Kurulumun tamamı bu — parametre, modele hiçbir mutlak yol gömülmesin diye var.

Hazır bir demo ihracı [`data/`](data/) içinde geliyor; rapor daha ilk yenilemede anlamlı sayılar gösterir. **Gerçek ERP ihracı varsayılan olarak güvenli bir yere gider:** `export-powerbi`, `-o` vermezseniz `powerbi/data.local/` (gitignore'lu) klasörüne yazar; böylece sonraki bir `git commit` sipariş tutarlarınızı, cari adlarınızı veya SQL'inizi asla yayınlayamaz. Gerçek veriyle çalışırken `DataFolder`'ı `powerbi\data.local`'e yöneltin; commit'li `data/` klasörü demo anlık görüntüsü olarak kalır.

## İçinde ne var?

| Parça | Teknoloji | Ne yapıyor |
|---|---|---|
| `ERP Command Center.SemanticModel/` | **TMDL** | Yıldız şema (2 fact, 2 boyut), 4 meta tablo, açıklamalı ve klasörlü 23 DAX ölçüsü, `discourageImplicitMeasures` |
| `Time Shift` tablosu | **Hesaplama grubu** | *Önceki Hafta / Haftalık Değişim / Haftalık % / 8 Haftalık Taban / Tabana Göre %* dönüşümlerini HERHANGİ bir ölçüye uygula — hafta aritmetiği boşluksuz sıra numarasında koşar, yıl sınırında asla kırılmaz |
| `Selected KPI` tablosu | **Alan parametresi** | Tek grafik, dört KPI — dört kopya görsel yerine izleyici kendisi değiştirir |
| `Revenue/On-Time Sparkline`, `Cover Bar` | **DAX SVG mikro-grafikleri** | `data:image/svg+xml` döndürüp `dataCategory: ImageUrl` etiketlenen ölçüler — tablo her satıra bir grafik çizer: **müşteri başına 13 haftalık sparkline** ve **ürün başına karşılama çubuğu** (eşiğin altında kırmızı, eşikte amber işaret). Özel görsel yok |
| `measurement-honesty-theme.json` | **Koyu tema** | Fütüristik koyu tema (Microsoft'un resmi tema şemasına karşı doğrulandı): yuvarlatılmış cam kartlar, yumuşak gölgeler, koyu yüzey için basamaklanmış renk-körü-güvenli kategorik palet |
| `ERP Command Center.Report/` | **PBIR** | 4 sayfa, 24 görsel, koyu tema — her görsel ayrı ve incelenebilir bir JSON |
| `tools/generate_report_pages.py` | **Kod-olarak-rapor** | Rapor sayfaları kompakt spec'lerden *üretilir*; yerleşim değişikliği = bir düzenleme + bir çalıştırma |
| `data/` | CSV yıldız şema | `export-powerbi` tarafından, motorun bekçili-denetimli-salt-okunur yolundan yazılır |

## Dört sayfa

1. **Overview** — **son tamamlanmış ISO haftasına** çapalı başlık kartları (iki günlük bir hafta asla çöküş gibi görünemez), haftalık ciro ve zamanında sevkiyat trendleri, DAX'in canlı hesapladığı sade dilli *Weekly Verdict* kartı.
2. **Drivers** — ciro üstünde ayrıştırma ağacı (bölge → müşteri → durum) + haftalık değişim tablosu; burada **her müşteri kendi 13 haftalık ciro sparkline'ını taşır** (DAX'in çizdiği SVG mikro-grafik): hareket nerede yoğunlaşıyor *ve* her hesap oraya nasıl geldi.
3. **Stock** — **ürün başına karşılama çubuğu** (SVG, eşiğin altında kırmızı) içeren karşılama haftası tablosu ve sipariş miktarı sıralaması; düşük-karşılama eşiği DAX'e gömülü değil, motorun config'inden `MetaRunInfo` üzerinden gelir.
4. **Trust** — imza sayfa: **kaynak mutabakat sayıları, her veri kalitesi bulgusu ve SQL denetim izinin tamamı** görsel olarak. Pano makbuzlarını gösterir.

## Tasarımı gereği proaktif

Model, motorun içgörü kurallarını DAX'te yeniden türetir — `insights.py` ile aynı eşikler (ciro |%5| haftalık, zamanında sevkiyat 1,5 puan), tek tanım iki yüzey:

- **`Alert Count`** — şu anda kaç kural ateşliyor (çalışma hafızasındaki ciro düşüş serisi dahil)
- **`Weekly Verdict`** — tek satırlık hikaye: *"Week 2026-W28: revenue +25.4% WoW · on-time −2.0 pts · 4 items below 2.0 weeks of cover"*
- **`Trust Statement`** — YALNIZCA her varlığın satır sayısı kaynaktaki `COUNT(*)` ile mutabıksa olumlu konuşur

`export-powerbi` komutunu haftalık `run` komutunun hemen arkasına zamanlayın (aynı Görev Zamanlayıcı / cron işi) — sayılar kendini yeniler; telefonunuza veri uyarısı isterseniz Power BI Service'e yayınlayın.

## Doğrulama — elle yazılmış bir PBIP nasıl doğru kalır?

Proje, Power BI Desktop'ı görmeden önce üç katmanda kontrol edilir:

1. `pytest tests/test_powerbi.py` — ihraç sözleşmesi (benzersiz anahtarlar, boşluksuz hafta sırası, BOM yok) + proje bütünlüğü (sayfa/görsel adlandırma kuralları, **görsel çakışma tespiti**, tema çözümleme, görsellerdeki her varlığın TMDL'de var olması).
2. [`pbir-cli`](https://pypi.org/project/pbir-cli/): `pbir validate "ERP Command Center.Report" --fields --qa` — resmi JSON şemaları + **yüklü TMDL modele karşı alan bağlama doğrulaması** (SVG mikro-grafik ölçüleri dahil 42 alan referansı kontrol edildi).
3. Power BI Desktop açılışta tüm PBIR dosyalarını kendisi de doğrular.

## Dürüst sınırlar

- **Desktop gerekli.** PBIP, Windows'ta (ücretsiz) Power BI Desktop ile açılır; depo bilerek `.pbix` ikilisi taşımaz — mesele zaten metin formatları.
- **Buradaki zamanında sevkiyat OTIF-lite** — motorun HTML raporuyla aynı tanım, aynı dipnot.
- Demo verisi sentetiktir. Ekili hikaye (bölgesel ciro sıçraması, geç sevkiyat kümesi, dört kirli satır) her sayfanın dürüstçe gösterecek bir şeyi olsun diye var.
