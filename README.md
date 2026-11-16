# Taşıyıcı Seçimi

Bir konteyner siparişi için en uygun taşıyıcı firmayı seçen ve seçimin gerekçesini Türkçe yazan uygulama.
REST API, firma yönetimi, teklif ekranı ve sıralama kurallarının düzenlendiği bir sayfadan oluşur.

Seçimi belirleyen her şey (kısıtlar, ücret, mesafe, sıralama) deterministik koddadır. TypeSafe Jev yalnızca
serbest metni anlamak için kullanılır; firma seçmez, ücret ya da mesafe hesaplamaz.

Python 3.12 · FastAPI · PostgreSQL 16 · Jinja2 + HTMX · Docker Compose


## Çalıştırma

```bash
cp .env.example .env    # giriş hesabı (ADMIN_EMAIL, ADMIN_PASSWORD) ve TYPESAFE_API_KEY
make run                # PostgreSQL ve uygulama Docker'da ayağa kalkar
make case-orders        # 7 örnek siparişi çalışan uygulamaya gönderir
```

- Vitrin: http://localhost:8000/ (girişsiz)
- Firmalar, Teklif, Kurallar: http://localhost:8000/admin/carriers (giriş gerekir)
- API dokümanı: http://localhost:8000/docs


## Nasıl çalışır

1. Şehirler bilinen bir ABD şehrine çözülür; bulunamayan şehir tahmin edilmez, öneriyle geri döner.
2. Boş bırakılan konteyner ölçüsü veya yük tipi açıklamadan çıkarılır: önce düzenli ifade, sonra Jev.
3. Mesafe önce mesafe tablosundan (`config/distances.yaml`), tabloda yoksa OpenRouteService'ten alınır.
4. Her firma zorunlu kısıtlardan geçer: mesafe aralığı, konteyner ölçüsü, yük tipi.
5. Siparişte açıklama varsa Jev, açıklamanın hangi firmayla çeliştiğini ve belirli bir firma istenip
   istenmediğini tek istekte söyler; çelişen firma elenir.
6. Kalan firmalar sırayla dizilir: toplam ücret, sonra merkezin çıkış noktasına uzaklığı, en son ad.
7. Sonuç; seçilen firma, sıralama, elenenler ve her birinin gerekçesiyle döner.


## Önemli kararlar

- Karar kodda, Jev yalnızca metinde: aynı sipariş her zaman aynı sonucu vermeli, test edilebilmeli ve
  açıklanabilmeli. Jev'in her cevabı güven değeriyle birlikte API yanıtında görünür.
- Ağırlıklı puan yerine öncelik sırası: bir kriter yalnızca üstündekiler eşitse devreye girer, böylece
  yakınlık hiçbir zaman daha ucuz bir firmanın önüne geçemez.
- Kurallar dosyada: sıralama önceliği, yük tipleri ve güven eşikleri `config/rules.yaml`'dadır. Kurallar
  sayfasından sürükle-bırak ile değiştirilir, yeniden başlatma gerekmez.
- Mesafe tablosu önceliklidir: harita servisi tablodan yüzde 3'e kadar sapıyor ve bu fark fiyatları
  değiştiriyor; servis yalnızca tabloda olmayan rotalar için kullanılır.
- Emin olunmayan yerde tahmin yok: Jev'in güveni 0,85'in altındaysa sonuç incelemeye düşer, 0,60'ın
  altındaysa bilgi istenir. Tehlikeli yük olasılığı 0,15'i geçerse her zaman incelemeye düşer.
- Girilen bilgi sessizce değiştirilmez: açıklama girilen yük tipiyle çelişirse kullanıcıya sorulur;
  bilinmeyen API alanı reddedilir.
- Jev maliyeti düşük: sorular tek istekte toplanır, açıklamasız sipariş Jev'e hiç gitmez, aynı soru
  24 saat bellekten cevaplanır.
- ORM yok: üç küçük tablo ve basit sorgular için parametreli SQL yeterli. PostgreSQL dizileri, `NUMERIC`
  ve `CHECK` kısıtları doğrudan kullanılır; veritabanı erişimi bir arayüzün arkasında olduğu için gerekirse
  yalnızca o katman değişir.


## Kod değiştirmeden yapılabilenler

- Firma eklemek, düzenlemek, silmek (konteyner ölçüsü serbest, 1–99 ft).
- Sıralama önceliğini değiştirmek, örneğin ücreti ikinci plana almak.
- Yeni yük tipi eklemek ve güven eşiklerini ayarlamak (`config/rules.yaml`).


## Testler

```bash
make test        # 508 test; veritabanı, ağ ve Jev gerekmez
make test-db     # 29 test, PostgreSQL'e karşı
```

Testlerde Jev ve harita servisi sahtedir; 7 örnek sipariş birim, API ve uçtan uca testlerde doğrulanır.


## Varsayımlar

- "Çıkış noktasına en yakın", firma merkezinin çıkış şehrine uzaklığıdır.
- Mesafe sınırları dahildir; boş sınır sınırsız demektir.
- Yalnızca ABD şehirleri; bir teklif tek konteyner içindir.
- Güven eşikleri başlangıç değerleridir, etiketli veriyle kalibre edilmedi.
