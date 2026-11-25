# umulauncher

Небольшой лаунчер Windows-игр для Linux на GTK4/libadwaita, который запускает игры
через [umu-launcher](https://github.com/Open-Wine-Components/umu-launcher).

Без Steam, без Electron и без pip-зависимостей: только Python 3.11+, PyGObject и
системный `umu-run`.

## Возможности

- Библиотека игр с обложками (SteamGridDB по API-ключу, Steam CDN как резерв).
- Запуск через `umu-run` с корректной санитизацией окружения (можно запускать
  даже из ярлыка Steam: `STEAM_COMPAT_*` и `PRESSURE_VESSEL_*` вычищаются).
- Выбор Proton: установленные сборки из `compatibilitytools.d`,
  `steamapps/common`, `/usr/share/steam`, плюс авто-варианты `UMU-Proton` и
  `GE-Proton` (скачивается umu сам).
- Менеджер Proton: список установленных сборок с размером, скачивание
  GE-Proton, UMU-Proton, Proton-CachyOS, DWProton и Proton Salkim (Wineland)
  с GitHub и dawn.wine — каждый источник отдельным списком, с прогрессом,
  докачкой, проверкой SHA512 и безопасным удалением.
- Редактирование игры без удаления: название, `.exe`, рабочая папка и папка
  префикса меняются прямо на странице игры.
- Управление префиксами: выбор папки, создание, размер на диске, открытие в
  файловом менеджере, безопасное удаление.
- Поиск GAMEID по названию в `umu-database` (включает protonfixes).
- Переменные окружения на игру, аргументы запуска, MangoHud, gamescope.
- Живой лог игры, история логов, `winetricks` в префикс.
- Экспорт `.desktop`-ярлыков, headless-запуск `umulauncher --run ID`.
- Русский и английский интерфейс (gettext).

## Требования

- Arch/CachyOS: `sudo pacman -S umu-launcher python-gobject gtk4 libadwaita`
- Опционально: `gamescope`, `mangohud`, `winetricks`
- Один рабочий Proton: UMU-Proton скачивается автоматически при первом запуске.

## Запуск из исходников

```bash
cd ~/umulauncher
make i18n          # собрать .mo (нужен gettext)
python3 -m umulauncher
```

Установка (без pip):

```bash
make install       # копия в ~/.local/share/umulauncher + ~/.local/bin/umulauncher
umulauncher        # если ~/.local/bin в PATH
make uninstall
```

Для установки в `~/.local/bin` нужен `gettext` (есть в базовой системе Arch).

### Бинарный пакет (Arch/CachyOS)

Готовый пакет лежит в GitHub Releases. Скачайте его и установите локально:

```bash
curl -LO https://github.com/barsuk228332/umu-launcher-gtk/releases/download/v0.1.0/umulauncher-0.1.0-1-any.pkg.tar.zst
sudo pacman -U umulauncher-0.1.0-1-any.pkg.tar.zst
```

Зависимости (`python`, `python-gobject`, `gtk4`, `libadwaita`, `umu-launcher`)
`pacman` подтянет сам из подключённых репозиториев.

Устанавливать сразу по URL (`sudo pacman -U https://...`) не получится при
стандартном `SigLevel = PackageRequired`: pacman ждёт рядом с пакетом файл
`.sig`, а его в релизе нет. Варианты — скачать пакет локально (выше) или
добавить `--nosignature`:

```bash
sudo pacman -U --nosignature https://github.com/barsuk228332/umu-launcher-gtk/releases/download/v0.1.0/umulauncher-0.1.0-1-any.pkg.tar.zst
```

Собрать пакет из исходников: `makepkg -si` (или `makepkg`, затем
`sudo pacman -U umulauncher-*.pkg.tar.zst`).

## Использование

1. Нажмите «+» и выберите `.exe` игры.
2. Проверьте Proton (по умолчанию — UMU-Proton). Кнопка загрузки рядом с
   Proton и пункт меню «Сборки Proton» открывают менеджер: там можно скачать
   GE-Proton, UMU-Proton, Proton-CachyOS, DWProton или Proton Salkim и удалить
   ненужные сборки.
3. Нажмите «Играть». Первый запуск дольше: umu готовит runtime/Proton.
4. Для сохранений и установщиков создайте префикс кнопкой «Создать префикс».

Установка игры через установщик: выберите `setup.exe` как игру, запустите её,
после установки замените путь на основной `.exe` (префикс сохраняется).

## CLI

```bash
python3 -m umulauncher --list          # id, название, GAMEID, Proton
python3 -m umulauncher --run 3         # запуск без окна (для .desktop)
python3 -m umulauncher --run 3 --debug # с UMU_LOG=1
```

## Где лежат данные

| Что | Путь |
|---|---|
| Библиотека | `~/.local/share/umulauncher/library.db` |
| Обложки | `~/.local/share/umulauncher/covers/` |
| Логи | `~/.local/share/umulauncher/logs/` |
| Настройки | `~/.config/umulauncher/config.json` (0600) |
| Proton, скачанный лаунчером | `~/.local/share/umu/compatibilitytools/` |
| Незавершённые загрузки Proton | `~/.cache/umulauncher/proton-downloads/` |
| Кэш umu-database | `~/.cache/umulauncher/umu-database.csv` |

## Решение проблем

- **Игра не стартует, в логе `default_pfx` / `Default prefix is missing`** —
  сборка Proton неполная. Проверьте, что у сборки есть
  `files/share/default_pfx`, или выберите UMU-Proton/GE-Proton.
- **Запуск зависает на скачивании `amdxcffx64.dll`** — это баг protonfixes в
  `proton-cachyos` (скачивание FSR4 с таймаутом 10 с). Используйте UMU-Proton,
  другую сборку Proton или дождитесь скачивания.
- **Нужно отключить protonfixes** — добавьте в переменные игры
  `PROTONFIXES_DISABLE=1`.
- **Запуск из ярлыка Steam** — лаунчер сам удаляет `STEAM_COMPAT_*`,
  `PRESSURE_VESSEL_*`, `SteamAppId` и `LD_PRELOAD`.
- **Проверить окружение** — включите «Отладочные логи» в настройках или
  запустите с `--debug`: в лог попадают команда, префикс и версия Proton.

## Разработка

```bash
make test     # unittest, без внешних зависимостей
make pot      # обновить po/umulauncher.pot
make i18n     # скомпилировать po/ru.po и po/en.po
```

Структура:

```
umulauncher/core/    бизнес-логика (db, protons, runner, prefixes, umudb, covers)
umulauncher/ui/      GTK4/libadwaita интерфейс
tests/               unit-тесты
po/                  переводы
```

## Лицензия

GNU General Public License v3.0 или новее (GPL-3.0-or-later). Полный текст —
в файле [LICENSE](LICENSE).
