# M-Modus TV

Mi Box (Android TV) və Android telefon üçün üç proqram və kanal siyahısı:

| Proqram | Harada | Nə edir |
|---|---|---|
| **M-Modus TV** (`M-ModusTV.apk`) | Box və telefon | IPTV: Azərbaycan, Türkiyə, Rusiya kanalları, TV proqramı, fayl meneceri |
| **M-Modus Brauzer** (`M-ModusBrauzer.apk`) | Box | Saytlar, video, yükləmələr; pultla kursor |
| **M-Modus Pult** (`M-ModusPult.apk`) | Telefon | TV-ni və Brauzeri idarə edir, telefonun klaviaturası ilə yazır, fayl göndərir |

Telefondan qoşulma M-Modus TV-də açılıb-bağlanır (Ayarlar → Telefon və kompüter) və istifadəçi adı ilə şifrə tələb edir. Eyni ayar Brauzer üçün də keçərlidir.

## Fayllar

| Fayl | Nə üçündür |
|---|---|
| `M-ModusTV.apk` | Proqramın son versiyası |
| `M-ModusBrauzer.apk`, `M-ModusPult.apk` | Brauzer və Pult |
| `version.json`, `version-web.json` | M-Modus TV və Brauzer yeni versiyanı buradan yoxlayır |
| `playlists/modus.m3u` | Bütün işləyən kanallar (Azərbaycan, Türkiyə, Rusiya) |
| `playlists/az.m3u`, `tr.m3u`, `ru.m3u` | Ölkələr üzrə ayrıca siyahılar |
| `report.md` | Gündəlik hesabat: neçə kanal işləyir, hansılar işləmir |
| `channels/config.json` | Hansı ölkələr və mənbələr istifadə olunur |
| `channels/overrides.json` | Əllə düzəlişlər: ad dəyişmək, gizlətmək, kanal əlavə etmək |

## Kanal siyahısı necə yenilənir

Hər gün avtomatik (GitHub Actions, 06:17 Bakı vaxtı):

1. iptv-org və Free-TV-dən ən son linklər götürülür.
2. Eyni kanal birləşdirilir; bir kanalın bir neçə linki varsa, ilk işləyən əsas olur, qalanları ehtiyat kimi saxlanılır (proqram əsas link açılmasa onlara özü keçir).
3. Bütün linklər yoxlanılır, siyahıya yalnız işləyənlər düşür.
4. Bu gün işləməyən kanal silinmir: işləyən kimi növbəti gün özü qayıdır.

Əllə işə salmaq: **Actions → Kanal siyahısını yenilə → Run workflow**.

## Yeni versiya buraxmaq

1. Yeni `M-ModusTV.apk` faylını yükləyin.
2. `version.json`-da `versionCode` rəqəmini artırın.

M-Modus TV bunu 12 saat ərzində görüb yeniləməni təklif edəcək.
