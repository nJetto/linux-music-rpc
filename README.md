# Linux Music RPC

Мост между музыкой, которая играет в Linux, и **Discord Rich Presence**.

Программа отслеживает активный трек через **MPRIS** (`playerctl`) и показывает его в профиле Discord как активность типа **«Слушает»**: название, исполнителя, альбом, обложку, прогресс и кнопку «Открыть трек».

Работает с Spotify, Яндекс Музыкой в браузере, Chromium/Chrome/Firefox, VLC, mpv, Rhythmbox, Elisa, Strawberry, Audacious, Cider, TIDAL, Deezer и любым другим плеером, который публикует MPRIS в D-Bus.

> Ориентир по функциональности — [WinYandexMusicRPC](https://github.com/FozerG/WinYandexMusicRPC), но это не порт: Linux-версия построена вокруг системного MPRIS и поэтому поддерживает любые плееры, а не только Яндекс Музыку.

---

## Содержание

- [Возможности](#возможности)
- [Как это работает](#как-это-работает)
- [Требования](#требования)
- [Быстрый старт](#быстрый-старт)
- [Установка](#установка)
  - [Arch Linux и производные](#arch-linux-и-производные)
  - [Универсальный установщик](#универсальный-установщик)
  - [Установка в систему](#установка-в-систему)
  - [Через pip / pipx](#через-pip--pipx)
  - [Запуск без установки](#запуск-без-установки)
- [Настройка приложения Discord](#настройка-приложения-discord)
- [Конфигурация](#конфигурация)
  - [Пример](#пример)
  - [Параметры](#параметры)
  - [Шаблоны строк](#шаблоны-строк)
- [Выбор плеера](#выбор-плеера)
- [Обложки](#обложки)
- [Автозапуск через systemd](#автозапуск-через-systemd)
- [Команды CLI](#команды-cli)
- [Проверка и диагностика](#проверка-и-диагностика)
- [Решение проблем](#решение-проблем)
- [Ограничения и отличия от WinYandexMusicRPC](#ограничения-и-отличия-от-winyandexmusicrpc)
- [Удаление](#удаление)
- [Разработка](#разработка)
- [Лицензия](#лицензия)

---

## Возможности

- **Любой MPRIS-плеер**, а не только Яндекс Музыка.
- **Без Python-зависимостей**: только стандартная библиотека Python 3.9+.
- **Прямая работа с Discord IPC**: официальный клиент, Flatpak, Snap, Vesktop и совместимые клиенты.
- **Rich Presence типа Listening** с названием, исполнителем и альбомом.
- **Прогресс трека** — полоса времени в профиле Discord, с учётом паузы и перемотки.
- **Обложки**: прямой URL из MPRIS или поиск в iTunes Search API, с дисковым кэшем.
- **Кнопка на трек**, если плеер отдаёт ссылку (`xesam:url`).
- **Пауза**: трек остаётся в статусе с пометкой «Пауза» (настраивается).
- **Очистка статуса**, когда музыка остановлена или программа завершается.
- **Приоритет и игнорирование плееров** — можно выбрать Spotify вместо браузера или скрыть mpv.
- **Один экземпляр** — защита от двух копий, борющихся за статус.
- **systemd user service** и готовый локальный `PKGBUILD`.
- **Диагностика**: `--check`, `--once`, `--list-players`, `--dry-run`.

---

## Как это работает

```text
┌─────────────────────┐     MPRIS / D-Bus      ┌──────────────────┐
│ Spotify, браузер,   │ ─────────────────────> │    playerctl     │
│ VLC, mpv, ...       │                        └────────┬─────────┘
└─────────────────────┘                                 │ метаданные
                                                        v
                                               ┌──────────────────┐
                                               │ linux-music-rpc  │
                                               │  выбор трека     │
                                               │  шаблоны, время  │
                                               │  обложка         │
                                               └────────┬─────────┘
                                                        │ Discord IPC
                                                        v
                                               ┌──────────────────┐
                                               │ Discord desktop  │
                                               │ Rich Presence    │
                                               └──────────────────┘
```

Программа раз в секунду (по умолчанию) вызывает `playerctl -a metadata`, выбирает подходящий трек, собирает объект активности и отправляет его в Discord через Unix-сокет `discord-ipc-N`. Соединение переиспользуется; при недоступности Discord выполняются повторные попытки.

---

## Требования

- Linux с графической сессией и D-Bus.
- Python **3.9+**.
- [`playerctl`](https://github.com/altdesktop/playerctl) — единственная системная зависимость.
- Запущенный **Discord desktop** (не веб-версия). Поддерживаются официальный клиент, Flatpak, Snap, Vesktop и другие клиенты с Discord IPC.
- Numeric **Application ID** вашего Discord-приложения (создаётся бесплатно, бот не нужен).

Проверить версии:

```bash
python3 --version
playerctl --version
```

Установка `playerctl`:

| Дистрибутив | Команда |
|---|---|
| Arch / Manjaro / EndeavourOS | `sudo pacman -S playerctl` |
| Debian / Ubuntu / Mint | `sudo apt install playerctl` |
| Fedora | `sudo dnf install playerctl` |
| openSUSE | `sudo zypper install playerctl` |
| Alpine | `sudo apk add playerctl` |

---

## Быстрый старт

```bash
# 1. Установить для текущего пользователя
./install.sh

# 2. Создать конфиг
linux-music-rpc --init

# 3. Вставить Application ID в ~/.config/linux-music-rpc/config.ini
$EDITOR ~/.config/linux-music-rpc/config.ini

# 4. Проверить окружение и handshake с Discord
linux-music-rpc --check

# 5. Запустить вручную
linux-music-rpc

# 6. Включить автозапуск (необязательно)
systemctl --user enable --now linux-music-rpc.service
```

Если `~/.local/bin` отсутствует в `PATH`, добавьте его в профиль оболочки:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## Установка

### Arch Linux и производные

В каталоге проекта есть локальный `PKGBUILD`. Он собирает пакет из текущих исходников, без скачивания архива.

```bash
sudo pacman -S --needed base-devel python playerctl
makepkg -si
```

После установки пакет доступен как `/usr/bin/linux-music-rpc`, модули лежат в `/usr/lib/linux-music-rpc`, а user unit — в `/usr/lib/systemd/user/linux-music-rpc.service`.

Дальше для каждого пользователя:

```bash
linux-music-rpc --init
$EDITOR ~/.config/linux-music-rpc/config.ini
linux-music-rpc --check
systemctl --user enable --now linux-music-rpc.service
```

> `PKGBUILD` устанавливает только системные файлы. Пользовательский конфиг и включение сервиса выполняются отдельно.

### Универсальный установщик

`install.sh` работает на любом дистрибутиве с Bash, Python 3.9+ и `playerctl`.

```bash
./install.sh
```

Что делает установщик в пользовательском режиме:

- копирует Python-модуль в `~/.local/share/linux-music-rpc`;
- создаёт launcher `~/.local/bin/linux-music-rpc`;
- создаёт `~/.config/linux-music-rpc/config.ini` (если файла ещё нет);
- создаёт `~/.config/systemd/user/linux-music-rpc.service`;
- при наличии `systemctl` делает `daemon-reload`.

Полезные опции:

```bash
./install.sh --enable-service   # сразу включить сервис
./install.sh --force-config     # перезаписать существующий config.ini
./install.sh --skip-deps        # не падать, если playerctl не установлен
./install.sh --help
```

Если `client_id` ещё не задан, `--enable-service` включит сервис, но не запустит его — иначе он завершится с ошибкой конфигурации.

### Установка в систему

```bash
sudo ./install.sh --system
```

Файлы будут установлены в:

- `/usr/bin/linux-music-rpc`
- `/usr/lib/linux-music-rpc/`
- `/usr/lib/systemd/user/linux-music-rpc.service`
- `/usr/share/doc/linux-music-rpc/`
- `/usr/share/licenses/linux-music-rpc/`

Конфиг по-прежнему создаётся каждым пользователем отдельно через `linux-music-rpc --init`.

### Через pip / pipx

Пакет можно установить как обычный Python-проект. Runtime-зависимостей нет, но `playerctl` должен быть установлен системно.

```bash
# Изолированно (рекомендуется)
pipx install .

# Или в виртуальное окружение
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

На Arch и в других дистрибутивах с PEP 668 `pip install --user .` может быть заблокирован — используйте `pipx`, venv или `install.sh`.

После установки:

```bash
linux-music-rpc --init
linux-music-rpc --check
```

### Запуск без установки

Можно запускать прямо из дерева исходников:

```bash
./linux-music-rpc --init
./linux-music-rpc --check
./linux-music-rpc
```

Launcher добавляет текущий каталог в `PYTHONPATH` и вызывает `python3 -m music_rpc`.

---

## Настройка приложения Discord

Discord Rich Presence требует **Application ID**. Бот, токен и OAuth-приглашение не нужны.

1. Откройте <https://discord.com/developers/applications>.
2. Нажмите **New Application** и введите любое имя (оно будет отображаться как название приложения в статусе).
3. На странице **General Information** скопируйте **Application ID** — длинное число.
4. Вставьте его в конфиг:

   ```ini
   [discord]
   client_id = 123456789012345678
   ```

5. Убедитесь, что в Discord включено отображение активности:
   **Настройки пользователя → Игровая активность → Отображать текущую игру как сообщение о статусе**.

`Application ID` — это не Client Secret и не токен бота. Если вставить нечисловое значение, программа сообщит об ошибке.

Необязательно: в **Rich Presence → Art Assets** можно загрузить:

- `fallback_image` — запасную обложку;
- `playing_image` — маленький значок «играет»;
- `paused_image` — маленький значок «пауза».

Эти значки задаются **именем ассета**, а не URL. Внешние `http(s)`-ссылки Discord принимает только в большом изображении (`large_image`), поэтому обложка может быть ссылкой, а маленькие значки — только загруженными ассетами.

---

## Конфигурация

Путь по умолчанию:

```text
~/.config/linux-music-rpc/config.ini
```

С учётом XDG:

```text
$XDG_CONFIG_HOME/linux-music-rpc/config.ini
```

Создать конфиг:

```bash
linux-music-rpc --init
```

Перезаписать шаблоном:

```bash
linux-music-rpc --init --force
```

Узнать фактический путь:

```bash
linux-music-rpc --print-config-path
```

Указать другой файл:

```bash
linux-music-rpc --config /path/to/config.ini
```

Формат — INI (`configparser`), кодировка UTF-8. Комментарии должны занимать отдельную строку: inline-комментарии после значений не поддерживаются.

### Пример

```ini
[discord]
client_id = 123456789012345678

[presence]
poll_interval = 1.0
show_paused = true
show_progress = true
clear_when_stopped = true
clear_on_exit = true
details_format = {title}
state_format = {artist} — {album}
paused_text = ⏸ Пауза
button_label = Открыть трек

[players]
priority_players = spotify, yandexmusic, chromium, firefox
ignore_players = mpv

[artwork]
enabled = true
provider = auto

[logging]
level = info
```

### Параметры

#### `[discord]`

| Параметр | По умолчанию | Описание |
|---|---|---|
| `client_id` | пусто | **Обязателен.** Numeric Application ID из Discord Developer Portal. |
| `ipc_path` | пусто | Путь к Unix-сокету Discord. Пусто — автоматический поиск (официальный клиент, Flatpak, Snap, Vesktop). Если задан, автопоиск отключается. |
| `reconnect_interval` | `10` | Пауза между попытками подключиться к Discord, секунды (1–600). |

Пример явного сокета:

```ini
ipc_path = /run/user/1000/discord-ipc-0
```

#### `[presence]`

| Параметр | По умолчанию | Описание |
|---|---|---|
| `poll_interval` | `1.0` | Как часто опрашивать MPRIS, секунды (0.2–30). |
| `show_paused` | `true` | Показывать трек на паузе. Если `false`, при паузе статус очищается. |
| `clear_when_stopped` | `true` | Очищать статус, когда музыка остановлена или плеер закрыт. |
| `clear_on_exit` | `true` | Очищать статус при штатном завершении программы. |
| `paused_text` | `⏸ Пауза` | Текст, добавляемый к строке состояния на паузе. Пусто — без пометки. |
| `fallback_state` | `Неизвестный исполнитель` | Что показать, если нет ни исполнителя, ни альбома. |
| `details_format` | `{title}` | Шаблон первой строки. |
| `state_format` | `{artist} — {album}` | Шаблон второй строки. |
| `show_progress` | `true` | Показывать полосу прогресса для играющего трека. |
| `button_label` | `Открыть трек` | Подпись кнопки-ссылки. Пусто — кнопка отключена. Максимум 32 символа. |
| `min_update_interval` | `2.0` | Минимальный интервал между обновлениями статуса, секунды (0–60). |

Дополнительно на стороне клиента действует ограничение Discord: не более 5 обновлений за 20 секунд. Программа соблюдает его автоматически, поэтому при очень частой смене треков статус может обновиться с небольшой задержкой.

#### `[players]`

| Параметр | По умолчанию | Описание |
|---|---|---|
| `priority_players` | пусто | Приоритет плееров при выборе трека. Список через запятую или пробел. |
| `ignore_players` | пусто | Плееры, которые нужно игнорировать. Список через запятую или пробел. |

Поддерживаются точные имена и glob-шаблоны:

```ini
priority_players = spotify, yandexmusic, chromium, firefox*
ignore_players = mpv, vlc.instance_*
```

Правила выбора:

1. Играющий плеер всегда важнее приостановленного.
2. Затем учитывается порядок `priority_players`.
3. Без приоритетов сохраняется текущий плеер, чтобы статус не «прыгал» между вкладками.
4. Если ничего не подходит, берётся первый плеер из списка `playerctl`.

#### `[artwork]`

| Параметр | По умолчанию | Описание |
|---|---|---|
| `enabled` | `true` | Включить обложки. |
| `provider` | `auto` | `auto`, `direct`, `itunes` или `none`. |
| `fallback_image` | пусто | Имя запасного ассета из Discord Developer Portal. |
| `playing_image` | пусто | Имя маленького ассета «играет». |
| `paused_image` | пусто | Имя маленького ассета «пауза». |

Режимы `provider`:

- `auto` — использовать прямой `http(s)` URL из MPRIS; если его нет или он указывает на `file://`, искать в iTunes;
- `direct` — только прямой URL из MPRIS, без сетевых запросов;
- `itunes` — всегда искать обложку в iTunes (полезно для браузеров и локальных файлов);
- `none` — не показывать обложки.

#### `[logging]`

| Параметр | По умолчанию | Описание |
|---|---|---|
| `level` | `info` | `debug`, `info`, `warning` или `error`. |

Для подробного журнала можно также запустить программу с `-v` / `--verbose`.

### Шаблоны строк

В `details_format` и `state_format` доступны поля:

| Поле | Значение |
|---|---|
| `{title}` | Название трека |
| `{artist}` | Исполнители через запятую |
| `{album}` | Альбом |
| `{player}` | Отображаемое имя плеера, например `Spotify` |
| `{player_raw}` | Сырое MPRIS-имя, например `chromium.instance1234` |
| `{status}` | `playing`, `paused` или `stopped` |
| `{duration}` | Длительность в формате `3:45` или `1:02:03` |
| `{position}` | Текущая позиция в том же формате |

Примеры:

```ini
details_format = {title}
state_format = {artist} — {album}
```

```ini
details_format = {artist} — {title}
state_format = {player} • {album}
```

```ini
details_format = {title} [{duration}]
state_format = {artist}
```

Особенности:

- Discord ограничивает каждую строку **128 символами UTF-16**; длинные значения обрезаются с многоточием.
- Если поле пустое, лишние разделители (`—`, `•`, запятые) удаляются.
- Если шаблон синтаксически некорректен, используется он же как обычный текст — программа не падает.
- На паузе к строке состояния добавляется `paused_text` (по умолчанию `⏸ Пауза • ...`).
- Прогресс показывается только для играющего трека и только при `show_progress = true`.

---

## Выбор плеера

MPRIS-имя обычно выглядит как `player` или `player.instance1234`. Для браузеров с несколькими профилями или вкладками экземпляров может быть несколько.

Посмотреть доступные плееры:

```bash
linux-music-rpc --list-players
```

Или напрямую:

```bash
playerctl -l
```

Пример вывода `--list-players`:

```text
chromium.instance42    playing    Исполнитель — Название
spotify                paused     Другой исполнитель — Другая песня
```

Шаблоны в `priority_players` и `ignore_players`:

- `spotify` — точное имя;
- `chromium` — также совпадёт с `chromium.instance42` (префикс с точкой);
- `firefox*` — glob-шаблон;
- `*` — всё.

Игнорирование применяется до выбора трека. Если плеер одновременно попал в оба списка, он будет проигнорирован.

---

## Обложки

Источники:

1. **Прямой URL из MPRIS** (`mpris:artUrl`) — используется в режимах `auto` и `direct`. Так работают Spotify, Яндекс Музыка и некоторые другие плееры.
2. **iTunes Search API** — используется в режимах `auto` (если прямого URL нет) и `itunes`. Запрос выполняется в фоновом потоке, чтобы не задерживать обновление статуса.

Особенности:

- `file://`-обложки (типично для Chromium и Firefox) не отправляются в Discord напрямую — вместо них выполняется поиск в iTunes.
- Результаты кэшируются в `$XDG_CACHE_HOME/linux-music-rpc/artwork.json` (обычно `~/.cache/linux-music-rpc/artwork.json`). Кэш содержит до 500 записей и автоматически обрезается.
- Неудачные запросы не повторяются 10 минут.
- Для кнопки и обложки нужен интернет только при использовании iTunes. Режимы `direct` и `none` работают полностью локально.
- В iTunes отправляются название, исполнитель и альбом. Если это нежелательно, установите `provider = direct` или `provider = none`.
- Discord принимает внешний URL только в `large_image`. Маленькие значки `playing_image` / `paused_image` должны быть загруженными ассетами.

Если обложка не появляется, проверьте `linux-music-rpc --check` и запустите `--once` — там видно, нашлась ли ссылка.

---

## Автозапуск через systemd

Пользовательская установка создаёт unit:

```text
~/.config/systemd/user/linux-music-rpc.service
```

Системная установка — в:

```text
/usr/lib/systemd/user/linux-music-rpc.service
```

Управление:

```bash
systemctl --user daemon-reload
systemctl --user enable --now linux-music-rpc.service
systemctl --user status linux-music-rpc.service
journalctl --user -u linux-music-rpc.service -f
```

Остановить и отключить:

```bash
systemctl --user disable --now linux-music-rpc.service
```

Перезапустить после изменения конфига:

```bash
systemctl --user restart linux-music-rpc.service
```

Сервис запускается с `WantedBy=default.target` и `After=graphical-session.target`. Если Discord стартует позже, программа продолжит попытки подключения с интервалом `reconnect_interval`.

Особенности:

- Не включайте одновременно пользовательский сервис и ручной запуск: сработает защита от второго экземпляра.
- Для systemd-сервиса нужен доступ к пользовательской D-Bus-сессии. В обычной графической сессии он есть. В SSH-сессии без `DBUS_SESSION_BUS_ADDRESS` `playerctl` не увидит плееры.
- Не добавляйте `PrivateTmp=true` в unit: Discord может держать IPC-сокет в `/tmp`.
- Логи пишутся в journal, отдельный файл не создаётся.

---

## Команды CLI

```text
linux-music-rpc [OPTIONS]
```

| Команда | Назначение |
|---|---|
| `linux-music-rpc` | Запустить основной цикл. |
| `--init` | Создать конфиг из шаблона и выйти. |
| `--init --force` | Перезаписать существующий конфиг. |
| `--check` | Проверить Python, конфиг, `playerctl`, плееры, сокеты Discord, handshake и режим обложек. |
| `--list-players` | Показать доступные MPRIS-плееры и текущие треки. |
| `--once` | Один раз опросить плееры и напечатать JSON активности. |
| `--dry-run` | Работать без подключения к Discord; полезно для проверки выбора трека. |
| `--config PATH` | Использовать другой файл конфигурации. |
| `--client-id ID` | Временно переопределить Application ID. |
| `--print-config-path` | Напечатать путь к конфигу. |
| `-v`, `--verbose` | Включить debug-журнал. |
| `--version` | Показать версию. |

Примеры:

```bash
# Быстрая проверка без правки конфига
linux-music-rpc --check --client-id 123456789012345678

# Посмотреть, что было бы отправлено в Discord
linux-music-rpc --once

# Подробный dry-run
linux-music-rpc --dry-run -v
```

`--once` может выполнить синхронный поиск обложки в iTunes, поэтому в медленной сети команда может занять несколько секунд.

---

## Проверка и диагностика

Рекомендуемый порядок:

```bash
# 1. Есть ли playerctl и плееры
command -v playerctl && playerctl --version
playerctl -l
playerctl metadata --format '{{status}} | {{artist}} — {{title}}'

# 2. Есть ли конфиг и корректный client_id
linux-music-rpc --print-config-path
linux-music-rpc --check

# 3. Что выбрала программа
linux-music-rpc --once

# 4. Полный цикл без Discord
linux-music-rpc --dry-run -v
```

`--check` возвращает ненулевой код, если не найден `playerctl`, не задан `client_id` или не удался handshake с Discord.

---

## Решение проблем

### `playerctl: not found`

Установите `playerctl` для своего дистрибутива (см. [Требования](#требования)). Проверьте:

```bash
command -v playerctl
playerctl -l
```

### `MPRIS players: none` / «No active MPRIS players/tracks»

- Запустите музыку — многие плееры публикуют MPRIS только во время воспроизведения.
- Проверьте `playerctl -l` в той же графической сессии, где работает программа.
- Для **mpv** нужен плагин MPRIS, например пакет `mpv-mpris` в Arch:
  ```bash
  sudo pacman -S mpv-mpris
  ```
- В **Firefox** должна быть включена поддержка медиа-клавиш / Media Session. Обычно она работает по умолчанию; проверьте `media.hardwaremediakeys.enabled` в `about:config`.
- В **Chromium/Chrome** MPRIS появляется, когда вкладка реально воспроизводит звук. После закрытия вкладки плеер исчезает.
- **Яндекс Музыка** в браузере работает как обычная вкладка Chromium/Firefox. Отдельное приложение должно само поддерживать MPRIS.
- **VLC** публикует MPRIS, если установлен с поддержкой D-Bus (стандартные пакеты дистрибутивов).
- Если плеер работает в другом пользователе, контейнере или namespace, MPRIS может быть не виден.

### `Discord IPC socket not found`

- Discord **desktop** должен быть запущен и авторизован в том же пользователе.
- Discord в браузере не подходит: Rich Presence требует desktop-клиента.
- Поддерживаются официальный клиент, Flatpak, Snap, Vesktop и совместимые клиенты. Проверьте сокеты:
  ```bash
  ls -l "${XDG_RUNTIME_DIR:-/tmp}"/discord-ipc-* 2>/dev/null
  find "${XDG_RUNTIME_DIR:-/tmp}" -maxdepth 3 -name 'discord-ipc-*' 2>/dev/null
  ```
- Если сокет лежит в нестандартном месте, укажите его явно:
  ```ini
  [discord]
  ipc_path = /run/user/1000/discord-ipc-0
  ```
- Иногда помогает перезапуск Discord: он пересоздаёт сокет.

### `Discord error 4000: Invalid Client ID`

- В `client_id` должно быть **число** из **General Information**, а не Client Secret, не токен бота и не ID пользователя.
- Проверьте, что приложение не удалено в Developer Portal.
- Попробуйте `--client-id` с другим ID, чтобы исключить опечатку в конфиге.

### Статус не появляется в Discord

- Включите **Настройки → Игровая активность → Отображать текущую игру как сообщение о статусе**.
- Убедитесь, что смотрите свой профиль или профиль, где отображается активность; некоторые клиенты и настройки приватности скрывают её.
- Проверьте `linux-music-rpc --check`: handshake должен быть `OK`.
- Посмотрите журнал: `journalctl --user -u linux-music-rpc.service -f` или вывод при ручном запуске.
- После смены `client_id` перезапустите программу.

### Статус обновляется с задержкой

Это ожидаемо:

- опрос MPRIS — раз в `poll_interval` (по умолчанию 1 секунда);
- между отправками действует `min_update_interval` (по умолчанию 2 секунды);
- Discord ограничивает 5 обновлений за 20 секунд.

Не ставьте `min_update_interval = 0` без необходимости: это не ускорит статус из-за серверного лимита.

### Нет обложки

- Проверьте `provider`: для браузеров часто нужен `auto` или `itunes`.
- iTunes может не найти редкий трек, ремикс или локальную запись — это нормально.
- Внешняя ссылка работает только как большое изображение. Маленькие значки должны быть ассетами приложения.
- Discord кэширует изображения; смена обложки может отображаться не сразу.
- Очистите кэш, если подозреваете устаревшую запись:
  ```bash
  rm -f ~/.cache/linux-music-rpc/artwork.json
  ```

### Сервис падает сразу после запуска

```bash
systemctl --user status linux-music-rpc.service
journalctl --user -u linux-music-rpc.service -n 100 --no-pager
```

Частые причины:

- не задан `client_id`;
- `playerctl` не установлен;
- неверный путь в `ExecStart` после ручного переноса;
- сервис запущен вне графической сессии и не видит D-Bus;
- уже работает другой экземпляр (в журнале будет `Another Linux Music RPC instance is already running`).

Если сервис несколько раз завершился с ошибкой и systemd заблокировал автоперезапуск, сбросьте состояние:

```bash
systemctl --user reset-failed linux-music-rpc.service
systemctl --user restart linux-music-rpc.service
```

### `Another Linux Music RPC instance is already running`

Закройте ручной запуск или остановите сервис:

```bash
pkill -f 'music_rpc'
systemctl --user stop linux-music-rpc.service
```

Не запускайте две копии одновременно: они будут перезаписывать статус друг друга.

### Кириллица или эмодзи отображаются некорректно

Убедитесь, что конфиг сохранён в UTF-8. Программа читает и отправляет Unicode без преобразований; Discord ограничивает строки 128 символами UTF-16, и обрезка учитывает суррогатные пары.

---

## Ограничения и отличия от WinYandexMusicRPC

Проект сознательно остаётся небольшим CLI-инструментом.

| Возможность | Linux Music RPC | WinYandexMusicRPC |
|---|---|---|
| ОС | Linux | Windows |
| Источник музыки | Любой MPRIS-плеер | Приложение Яндекс Музыки (Windows) |
| Управление | CLI + systemd user service | GUI / трей (в оригинале) |
| Зависимости | Python 3.9+ и `playerctl` | Зависимости оригинального проекта |
| Discord | Rich Presence типа Listening | Rich Presence |
| Обложки | MPRIS URL + iTunes | Ориентировано на Яндекс Музыку |
| Специфика Яндекс Музыки | Нет | Есть |

Ограничения Linux-версии:

- **Только MPRIS.** Windows Media Session (SMTC), Apple Music API и проприетарные API плееров не поддерживаются.
- **Нет GUI и трея.** Настройка — через INI-файл, управление — через CLI и systemd.
- **Нет мобильного пульта, Ynison и прочих функций Яндекс Музыки.** Это не клиент Яндекс Музыки, а мост MPRIS → Discord.
- **Один активный трек.** Одновременно отображается только один выбранный плеер.
- **Нет управления воспроизведением.** Программа только читает метаданные, но не ставит паузу и не переключает треки.
- **Нет текстов песен, истории прослушивания и scrobbling.**
- **Discord web не поддерживается.** Нужен desktop-клиент.
- **Кнопка зависит от плеера.** Если MPRIS не отдаёт `xesam:url`, кнопки не будет.
- **Прогресс зависит от метаданных.** Некоторые плееры не сообщают позицию; тогда используется расчёт по времени с момента запуска трека.
- **Нет Flatpak-пакета самого приложения.** Поддерживается подключение к Discord, установленному через Flatpak, но само приложение ставится через `install.sh`, `PKGBUILD` или pip.
- **Нет автоматического обновления.** Обновление — вручную, через пакетный менеджер или повторную установку.

---

## Удаление

Пользовательская установка:

```bash
./uninstall.sh
```

Удалить также конфиг и кэш обложек:

```bash
./uninstall.sh --purge
```

Системная установка:

```bash
sudo ./uninstall.sh --system
```

При удалении без `--purge` конфиг `~/.config/linux-music-rpc/config.ini` и кэш `~/.cache/linux-music-rpc/` сохраняются.

Если пакет ставился через `makepkg -si`:

```bash
sudo pacman -Rns linux-music-rpc
```

Пользовательские конфиги при этом не удаляются.

---

## Разработка

Структура проекта:

```text
linux-music-rpc/
├── linux-music-rpc              # launcher из дерева исходников
├── music_rpc/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                   # основной цикл, rate limit, lock
│   ├── artwork.py               # обложки и кэш
│   ├── cli.py                   # CLI и диагностика
│   ├── config.py                # INI-конфиг
│   ├── config.example.ini       # шаблон конфига
│   ├── discord_ipc.py           # Discord IPC без зависимостей
│   ├── mpris.py                 # playerctl и выбор трека
│   └── presence.py              # сборка activity
├── packaging/
│   ├── launcher
│   └── linux-music-rpc.service
├── tests/
├── install.sh
├── uninstall.sh
├── PKGBUILD
└── pyproject.toml
```

Запуск тестов:

```bash
python3 -m unittest discover -s tests -v
```

Требования к коду:

- Python 3.9+, только стандартная библиотека;
- без сетевых вызовов в основном потоке (обложки — в фоновом);
- ошибки MPRIS и Discord не должны завершать программу;
- новые параметры конфига нужно добавлять в `config.py`, `config.example.ini`, тесты и эту документацию.

Проверка синтаксиса и быстрый smoke-test:

```bash
python3 -m compileall -q music_rpc
python3 -m music_rpc --list-players
python3 -m music_rpc --once
```

### Репозиторий

```text
https://github.com/nJetto/linux-music-rpc
```

---

## Лицензия

MIT. См. [LICENSE](LICENSE).

Проект не связан с Discord Inc. или Яндексом. Discord и Яндекс Музыка — товарные знаки соответствующих правообладателей.
