# 🕵️ NoRootSpy

> ⚠️ **ВНИМАНИЕ / WARNING**
>
> ---
>
> ### 🇷🇺 РУССКИЙ
>
> **ДАННОЕ ПРОГРАММНОЕ ОБЕСПЕЧЕНИЕ ПРЕДОСТАВЛЯЕТСЯ ИСКЛЮЧИТЕЛЬНО В ОБРАЗОВАТЕЛЬНЫХ И ОЗНАКОМИТЕЛЬНЫХ ЦЕЛЯХ.**
>
> Автор проекта **НЕ НЕСЁТ НИКАКОЙ ОТВЕТСТВЕННОСТИ** за любые последствия, возникшие в результате использования, модификации или распространения данного ПО. Используя этот проект, вы подтверждаете, что:
>
> - Ознакомлены с законодательством вашей страны/региона в области видеонаблюдения, записи и распространения мультимедиа;
> - Несёте **полную личную ответственность** за все действия, совершённые с использованием данного ПО;
> - Не будете применять данное ПО для нарушения приватности третьих лиц, несанкционированного доступа, шпионажа или любых иных противоправных действий;
> - Используете проект **исключительно** для изучения технологий потокового видео, WebSocket-коммуникации и работы с кодеками.
>
> **ЛЮБОЕ ИСПОЛЬЗОВАНИЕ ДАННОГО ПО В НЕЗАКОННЫХ ЦЕЛЯХ СТРОГО ЗАПРЕЩЕНО.**
>
> ---
>
> ### 🇬🇧 ENGLISH
>
> **THIS SOFTWARE IS PROVIDED SOLELY FOR EDUCATIONAL AND RESEARCH PURPOSES.**
>
> The author of this project bears **NO LIABILITY WHATSOEVER** for any consequences arising from the use, modification, or distribution of this software. By using this project, you acknowledge that:
>
> - You are familiar with the laws and regulations of your country/region regarding video surveillance, recording, and multimedia distribution;
> - You assume **full personal responsibility** for all actions performed using this software;
> - You will NOT use this software to violate the privacy of third parties, gain unauthorized access, conduct espionage, or engage in any other unlawful activities;
> - You are using this project **exclusively** to study video streaming technologies, WebSocket communication, and codec operations.
>
> **ANY USE OF THIS SOFTWARE FOR ILLEGAL PURPOSES IS STRICTLY PROHIBITED.**
>
> ---

---

## 📖 Описание / Description

### 🇷🇺

**NoRootSpy** — это легковесная система потокового вещания экрана, веб-камеры и системного звука в реальном времени через WebSocket с воспроизведением в браузере без необходимости установки плагинов или root-прав.

Архитектура построена на трёх компонентах:

| Компонент | Файл | Назначение |
|-----------|------|------------|
| **Сервер** | `server.py` | WebSocket-ретранслятор + HTTP-сервер веб-интерфейса |
| **Клиент-вещатель** | `client.py` | Захват экрана/камеры/аудио, кодирование H.264/AAC, отправка по WS |
| **Веб-интерфейс** | `server.html` / `server.js` / `server.css` | Просмотр потока через MSE (Media Source Extensions) |

### 🇬🇧

**NoRootSpy** is a lightweight real-time streaming system for screen, webcam, and system audio over WebSocket with in-browser playback via MSE — no plugins or root privileges required.

The architecture consists of three components:

| Component | File | Purpose |
|-----------|------|---------|
| **Server** | `server.py` | WebSocket relay + HTTP server for the web UI |
| **Broadcaster client** | `client.py` | Screen/camera/audio capture, H.264/AAC encoding, WS transmission |
| **Web UI** | `server.html` / `server.js` / `server.css` | Stream playback via MSE (Media Source Extensions) |

---

## ✨ Возможности / Features

### 🇷🇺

- 🖥️ Захват экрана (через `mss`) с настраиваемым разрешением и FPS
- 📷 Наложение веб-камеры поверх экрана (или как самостоятельный источник)
- 🔊 Захват системного звука / микрофона (через `sounddevice`)
- 🎞️ Кодирование **H.264 (Baseline)** + **AAC** с использованием `PyAV` (FFmpeg)
- 🌐 Передача по **WebSocket** с фрагментацией MP4 (`frag_keyframe + empty_moov`)
- 🖥️ Воспроизведение в браузере через **Media Source Extensions** — без плагинов
- 👥 Поддержка **нескольких вещателей** одновременно
- 🔐 Аутентификация зрителей (логин/пароль) и вещателей (токен)
- 🎛️ Переключение качества «на лету» (разрешение + FPS)
- 🔇 Переключение источника звука «на лету» (система / микрофон / выкл.)
- 🔄 Автоматическое переподключение клиента при обрыве связи
- 🐧 Кроссплатформенность: **Windows / Linux / macOS**
- ⚙️ Фоновый режим (`-fon`) и остановка (`-stop`) через PID-файл

### 🇬🇧

- 🖥️ Screen capture (via `mss`) with configurable resolution and FPS
- 📷 Webcam overlay on screen (or standalone source)
- 🔊 System audio / microphone capture (via `sounddevice`)
- 🎞️ **H.264 (Baseline)** + **AAC** encoding using `PyAV` (FFmpeg)
- 🌐 Transmission over **WebSocket** with fragmented MP4 (`frag_keyframe + empty_moov`)
- 🖥️ In-browser playback via **Media Source Extensions** — no plugins
- 👥 Support for **multiple simultaneous broadcasters**
- 🔐 Authentication for viewers (login/password) and broadcasters (token)
- 🎛️ Runtime quality switching (resolution + FPS)
- 🔇 Runtime audio source switching (system / mic / off)
- 🔄 Auto-reconnect on connection loss
- 🐧 Cross-platform: **Windows / Linux / macOS**
- ⚙️ Background mode (`-fon`) and stop (`-stop`) via PID file

---

## 📐 Архитектура / Architecture

```
┌──────────────────┐        WebSocket         ┌──────────────────┐
│   client.py      │◄────────────────────────►│   server.py      │
│  (Broadcaster)   │   /ws/broadcast          │   (Relay)        │
│                  │   H.264+AAC / MP4-frag   │                  │
│  mss → cv2 →    │                          │  ┌──────────────┐│
│  PyAV → WS      │                          │  │ HTTP :8080   ││
└──────────────────┘                          │  │ (Web UI)     ││
                                              │  └──────────────┘│
                                              │                  │
┌──────────────────┐        WebSocket         │  /ws/view        │
│   Browser        │◄────────────────────────►│  (auth required) │
│  MSE Playback    │                          │                  │
│  server.html/js  │                          └──────────────────┘
└──────────────────┘
```

---

## 📦 Установка / Installation

### 🇷🇺 Требования

- **Python 3.9+**
- **FFmpeg** (библиотеки `libx264`, `libaac`) — для работы `PyAV`
- Системные зависимости для `mss` и `sounddevice` (на Linux: `libx11`, `libpulse` / `libasound`)

### 🇬🇧 Prerequisites

- **Python 3.9+**
- **FFmpeg** (libraries `libx264`, `libaac`) — required by `PyAV`
- System dependencies for `mss` and `sounddevice` (on Linux: `libx11`, `libpulse` / `libasound`)

### Установка зависимостей / Install dependencies

```bash
pip install websockets av opencv-python mss numpy sounddevice
```

> 💡 На **Windows** пакет `sounddevice` обычно работает «из коробки».
> На **Linux** может потребоваться:
> ```bash
> sudo apt install portaudio19-dev libavcodec-dev libavformat-dev libswresample-dev
> ```

---

## 🚀 Запуск / Usage

### 1. Сервер / Server

```bash
# Обычный запуск
python server.py

# Фоновый режим (без терминала, вывод в /dev/null)
python server.py -fon

# Остановка фонового процесса
python server.py -stop
```

Сервер поднимает:
- **HTTP** на порту `8081` — веб-интерфейс
- **WebSocket** на порту `8765` — потоки данных

### 2. Клиент-вещатель / Broadcaster Client

```bash
# Обычный запуск
python client.py

# Фоновый режим
python client.py -fon

# Остановка
python client.py -stop
```

Перед запуском отредактируйте параметры в начале `client.py`:

```python
SERVER_IP       = "127.0.0.1"   # IP вашего сервера
PORT            = 8765
BROADCAST_TOKEN = "super_token_123"   # должен совпадать с сервером

TARGET_WIDTH    = 1280
TARGET_HEIGHT   = 720
TARGET_FPS      = 30

AUDIO_SOURCE    = "system"   # "system" | "mic" | "off"

ENABLE_SCREEN   = True       # захват экрана
ENABLE_WEBCAM   = True       # веб-камера
ENABLE_AUDIO    = True       # звук
```

### 3. Просмотр в браузере / Viewing in Browser

1. Откройте `http://<SERVER_IP>:8080`
2. Введите логин и пароль (по умолчанию `admin` / `admin`)
3. Выберите вещателя из списка
4. Нажмите **Enable Sound**, если нужен звук

---

## ⚙️ Конфигурация сервера / Server Configuration

В начале `server.py` задаются ключевые параметры:

```python
HTTP_PORT       = 8080
WS_PORT         = 8765
ADMIN_USER      = "admin"
ADMIN_PASS      = "admin"
BROADCAST_TOKEN = "super_token_123"
```

> ⚠️ **Обязательно смените** `ADMIN_PASS` и `BROADCAST_TOKEN` перед использованием в любой сети!

---

## 🎛️ Управление во время трансляции / Runtime Controls

| Действие | Как |
|----------|-----|
| Смена качества | Выпадающий список **Quality** → `1280×720@30` / `960×540@24` / `640×360@15` |
| Источник звука | Выпадающий список **Sound** → `System` / `Microphone` / `Off` |
| Вкл./выкл. звук | Кнопка **🔇 / 🔊** |
| Смена вещателя | Кнопка **Exit** → выбор из списка |

---

## 🧩 Структура проекта / Project Structure

```
NoRootSpy/
├── server.py          # WebSocket-сервер + HTTP
├── server.html        # Веб-интерфейс (шаблон)
├── server.js          # Логика MSE-плеера
├── server.css         # Стили (тёмная тема)
├── client.py          # Клиент-вещатель
├── website-source/    # Директория для статических файлов (если нужна)
├── server.pid         # PID сервера (создаётся при -fon)
├── client.pid         # PID клиента (создаётся при -fon)
└── README.md
```

---

## 🔧 Технические детали / Technical Details

### 🇷🇺

- **Контейнер**: фрагментированный MP4 (`frag_keyframe + empty_moov + default_base_moof`) — позволяет начать воспроизведение без ожидания полного файла.
- **Видеокодек**: H.264 Baseline Profile, Level 3.1, `ultrafast` preset, `zerolatency` tune.
- **Аудиокодек**: AAC-LC, 44100 Hz, stereo, блоки по 1024 сэмпла.
- **Синхронизация зрителя**: сервер дожидается первого `moof`-бокса перед отправкой данных, чтобы декодер получил ключевой кадр.
- **Буферизация**: на клиенте — очередь до 8 фрагментов; при переполнении старые кадры отбрасываются. На сервере — `safe_send` с таймаутом 200 мс.
- **Автоподстройка лага**: браузерный плеер автоматически «догоняет» поток, если задержка превышает 3 секунды.

### 🇬🇧

- **Container**: fragmented MP4 (`frag_keyframe + empty_moov + default_base_moof`) — enables playback without waiting for a complete file.
- **Video codec**: H.264 Baseline Profile, Level 3.1, `ultrafast` preset, `zerolatency` tune.
- **Audio codec**: AAC-LC, 44100 Hz, stereo, 1024-sample frames.
- **Viewer sync**: server waits for the first `moof` box before sending data so the decoder receives a keyframe.
- **Buffering**: client-side queue up to 8 fragments; oldest frames are dropped on overflow. Server-side `safe_send` with 200 ms timeout.
- **Auto lag compensation**: browser player auto-seeks forward when latency exceeds 3 seconds.

---

## 🐛 Устранение неполадок / Troubleshooting

| Проблема | Решение |
|----------|---------|
| `sounddevice` не импортируется | Установите PortAudio: `sudo apt install portaudio19-dev` (Linux) или проверьте разрядность Python |
| Чёрный экран в браузере | Убедитесь, что браузер поддерживает MSE (Chrome, Edge, Firefox). Safari имеет ограниченную поддержку |
| Высокая задержка (>5 с) | Понизьте качество до `640×360@15`; проверьте пропускную способность сети |
| Клиент не подключается | Проверьте `SERVER_IP`, `PORT`, `BROADCAST_TOKEN`; убедитесь, что фаервол не блокирует порт 8765 |
| «Codec error» в браузере | Браузер не поддерживает H.264 Baseline — используйте Chrome/Edge |

---

## 📜 Лицензия / License

Данный проект распространяется **исключительно в образовательных целях**.
Автор не предоставляет никаких гарантий и не несёт ответственности за любой ущерб, причинённый в результате использования данного ПО.

**Используя этот проект, вы принимаете на себя всю ответственность за соблюдение применимого законодательства.**

---

> 🛑 **Ещё раз напоминаем / Reminder:**
> Проект создан **для обучения**. Не используйте его для слежки, несанкционированного наблюдения или любых действий, нарушающих закон и права других людей.
>
> This project is for **educational purposes only**. Do not use it for surveillance, unauthorized monitoring, or any actions that violate the law or the rights of others.
```