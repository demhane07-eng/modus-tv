# M-Modus TV

Mi Box (Android TV) və Android telefon üçün IPTV proqramı və onun kanal siyahısı. Eyni APK hər iki cihazda işləyir: TV-də pultla, telefonda toxunuşla.

## Fayllar

| Fayl | Nə üçündür |
|---|---|
| `M-ModusTV.apk` | Proqramın son versiyası |
| `version.json` | Proqram yeni versiyanı buradan yoxlayır |
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
