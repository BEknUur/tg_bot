"""
PRIMA TA — Telegram Bot (финальная версия)
Квиз + напоминания + опрос после МК + Google Sheets + кнопка менеджера

Установка:
    pip install python-telegram-bot anthropic apscheduler gspread google-auth

Запуск:
    python prima_bot_final.py
"""

import os
import re
import asyncio
import logging
from datetime import datetime
import anthropic
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

load_dotenv()

logging.basicConfig(level=logging.INFO)

# ─── КОНФИГУРАЦИЯ ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_KEY")
GOOGLE_CREDS    = "credentials.json"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
MANAGER_URL     = "https://t.me/Prima_TA"
INSTAGRAM_RJ    = "https://instagram.com/rakhima.kuandykova"
MK_LINK         = os.getenv("MK_LINK", "")

if not TELEGRAM_TOKEN or not ANTHROPIC_KEY:
    raise RuntimeError("Не найдены TELEGRAM_TOKEN или ANTHROPIC_KEY в .env файле")
# ─────────────────────────────────────────────────────────────────────────────

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# Кнопка менеджера — используется везде где бот завершает диалог
def manager_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Написать менеджеру", url=MANAGER_URL)
    ]])

# Состояния диалога
(SELECT_TYPE, Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8,
 ASK_REGISTERED, ASK_REMINDER,
 POST_MK_ATTENDED, POST_MK_Q1, POST_MK_Q2, POST_MK_Q3, POST_MK_FREE) = range(16)

# ─── GOOGLE SHEETS ───────────────────────────────────────────────────────────

def get_sheets():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        return sh
    except Exception as e:
        logging.error(f"Google Sheets error: {e}")
        return None

def save_quiz_result(user, user_type, answers, result_name):
    try:
        sh = get_sheets()
        if not sh:
            return
        try:
            ws = sh.worksheet("Квиз")
        except:
            ws = sh.add_worksheet("Квиз", rows=1000, cols=20)
            ws.append_row([
                "Дата", "User ID", "Username", "Имя",
                "Тип аудитории",
                "Ответ 1","Ответ 2","Ответ 3","Ответ 4",
                "Ответ 5","Ответ 6","Ответ 7","Ответ 8",
                "Название результата"
            ])
        row = [
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            user.id,
            f"@{user.username}" if user.username else "—",
            user.full_name,
            user_type,
        ] + answers + [result_name]
        ws.append_row(row)
    except Exception as e:
        logging.error(f"Quiz save error: {e}")

def save_mk_data(user, data: dict):
    try:
        sh = get_sheets()
        if not sh:
            return
        try:
            ws = sh.worksheet("МК")
        except:
            ws = sh.add_worksheet("МК", rows=1000, cols=15)
            ws.append_row([
                "Дата", "User ID", "Username", "Имя",
                "Зарегистрирован", "Хотел напоминание",
                "Был на МК", "Оценка МК", "Что ценного",
                "Интерес к сообществу", "Свободный отзыв",
                "Передан менеджеру"
            ])
        row = [
            datetime.now().strftime("%d.%m.%Y %H:%M"),
            user.id,
            f"@{user.username}" if user.username else "—",
            user.full_name,
            data.get("registered", "—"),
            data.get("reminder", "—"),
            data.get("attended", "—"),
            data.get("mk_rating", "—"),
            data.get("mk_valuable", "—"),
            data.get("community_interest", "—"),
            data.get("free_feedback", "—"),
            data.get("sent_to_manager", "—"),
        ]
        ws.append_row(row)
    except Exception as e:
        logging.error(f"MK save error: {e}")

# ─── ТЕКСТЫ ──────────────────────────────────────────────────────────────────

INTRO_TEXT = """*PRIMA TA · Институт Транзактного Анализа*

Добро пожаловать.

Этот опросник разработан институтом PRIMA для того, чтобы вы могли остановиться и посмотреть на себя — в профессии или на пути к ней.

Он не даёт готовых ответов. Он создаёт пространство для размышления: что сейчас происходит, что за этим может стоять и куда это может вести.

По итогу вы получите персональные наблюдения ИИ-агента PRIMA — гипотетические, не являющиеся психологическим заключением. Это приглашение к размышлению, а не оценка.

Прежде чем начать — один вопрос:"""

TYPE_QUESTION = "Кто вы в отношении профессии психолога?"

TYPE_OPTIONS = [
    ["1. Практикующий психолог"],
    ["2. Обучающийся психолог"],
    ["3. Коуч или специалист помогающей профессии"],
    ["4. Думаю о том, чтобы стать психологом"],
]

# ─── ВОПРОСЫ ─────────────────────────────────────────────────────────────────

QUESTIONS = {
    1: [
        {"text": "Как давно вы практикуете?", "options": [
            ["а) Меньше года — только начинаю"],
            ["б) 1–3 года — в процессе становления"],
            ["в) 3–7 лет — практика есть, ищу глубины"],
            ["г) Более 7 лет — опыт есть, но что-то ускользает"],
        ]},
        {"text": "Что сейчас больше всего беспокоит в практике?", "options": [
            ["а) Клиентов мало — не понимаю как наработать базу"],
            ["б) Клиенты есть, но ощущение что топчусь на месте"],
            ["в) Практика есть, но устаю — и не понимаю почему"],
            ["г) Хочу расти, но не ясно в какую сторону"],
        ]},
        {"text": "Когда сессия идёт тяжело — что происходит внутри?", "options": [
            ["а) Тревога: правильно ли я делаю, помогаю ли"],
            ["б) Раздражение или скука — и потом стыд за это"],
            ["в) Пустота — как будто выключился/ась"],
            ["г) Захватывает вместе с клиентом — теряю себя"],
        ]},
        {"text": "Замечаете ли вы — что именно влияет на вас со стороны клиента?", "options": [
            ["а) Да, замечаю и могу это назвать"],
            ["б) Замечаю что-то, но обычно уже после сессии"],
            ["в) Чувствую что что-то происходит — но сложно понять что"],
            ["г) Обычно не задумываюсь об этом во время работы"],
        ]},
        {"text": "Есть ли клиент, с которым происходит что-то — что вы не можете назвать?", "options": [
            ["а) Да, и это меня беспокоит"],
            ["б) Да, есть версия — но я не уверен/а"],
            ["в) Бывало раньше, сейчас справляюсь лучше"],
            ["г) Нет, в контакте с клиентами у меня обычно есть ясность"],
        ]},
        {"text": "Откуда вы берёте опору между сессиями?", "options": [
            ["а) Личная терапия или регулярная практика"],
            ["б) Коллеги, профессиональная среда"],
            ["в) Честно — особо неоткуда"],
            ["г) Стараюсь не думать о работе вне работы"],
        ]},
        {"text": "Как вы понимаете, что сессия прошла хорошо?", "options": [
            ["а) Клиент говорит что помогло"],
            ["б) Есть ощущение контакта — что-то живое произошло"],
            ["в) Сделал/а всё технически правильно"],
            ["г) Честно — не всегда понимаю"],
        ]},
        {"text": "Если представить вашу практику через год — что важнее всего?", "options": [
            ["а) Больше клиентов и стабильный доход"],
            ["б) Глубина — работать сложнее, но точнее"],
            ["в) Устойчивость — не выгорать, оставаться собой"],
            ["г) Понимать себя как терапевта лучше, чем сейчас"],
        ]},
    ],

    2: [
        {"text": "На каком этапе вы сейчас?", "options": [
            ["а) Учусь, практики ещё нет совсем"],
            ["б) Начал/а практиковать параллельно с учёбой"],
            ["в) Закончил/а обучение, выстраиваю практику"],
            ["г) Давно учусь, но к практике страшно подступиться"],
        ]},
        {"text": "Что сейчас вызывает наибольшую тревогу в отношении практики?", "options": [
            ["а) Не знаю достаточно теории, чтобы работать с клиентом"],
            ["б) Боюсь навредить — сделать что-то не так"],
            ["в) Не понимаю, как выстроить контакт с реальным клиентом"],
            ["г) Тревожит, что клиент увидит мою неуверенность"],
        ]},
        {"text": "Когда представляете себя в сессии — что первое возникает внутри?", "options": [
            ["а) Интерес и желание помочь"],
            ["б) Тревога и неуверенность"],
            ["в) Желание сделать всё правильно"],
            ["г) Страх — а вдруг я не справлюсь"],
        ]},
        {"text": "Замечаете ли, как ваше состояние влияет на то, как вы слушаете другого?", "options": [
            ["а) Да, замечаю — и это меня беспокоит"],
            ["б) Иногда замечаю, но не всегда понимаю что с этим делать"],
            ["в) Стараюсь контролировать себя, чтобы это не мешало"],
            ["г) Не очень задумывался/ась об этом"],
        ]},
        {"text": "Есть ли в обучении то, что понимаете теоретически — но не чувствуете как своё?", "options": [
            ["а) Да, многое — теория есть, живого ощущения нет"],
            ["б) Частично — некоторые темы откликаются глубже"],
            ["в) Нет, я интегрирую всё через личную терапию"],
            ["г) Не задумывался/ась об этом разрыве"],
        ]},
        {"text": "Как относитесь к своим уязвимостям в контексте профессии?", "options": [
            ["а) Боюсь что они помешают быть хорошим/ей терапевтом"],
            ["б) Думаю что нужно их проработать до начала практики"],
            ["в) Считаю что это ресурс — если я их понимаю"],
            ["г) Стараюсь не думать об этом"],
        ]},
        {"text": "Есть ли рядом профессиональная среда для честного разговора?", "options": [
            ["а) Да, есть группа или сообщество"],
            ["б) Есть отдельные люди, но не система"],
            ["в) Нет, и я чувствую эту нехватку"],
            ["г) Не думал/а что это важно на моём этапе"],
        ]},
        {"text": "Что для вас означает «быть готовым/ой к практике»?", "options": [
            ["а) Знать достаточно теории и техник"],
            ["б) Пройти достаточно личной терапии"],
            ["в) Чувствовать внутреннюю устойчивость — опору в себе"],
            ["г) Честно — я не знаю как это определить"],
        ]},
    ],

    3: [
        {"text": "Как давно вы работаете с людьми в вашей профессии?", "options": [
            ["а) Меньше года — только начинаю"],
            ["б) 1–3 года — нахожусь в процессе"],
            ["в) Более 3 лет — есть опыт и клиенты"],
            ["г) Давно, но чувствую что упираюсь в потолок"],
        ]},
        {"text": "Что привело вас к интересу к психологии?", "options": [
            ["а) Хочу глубже понимать людей с которыми работаю"],
            ["б) Клиенты приходят с запросами которые выходят за рамки моей работы"],
            ["в) Хочу понять себя — чтобы лучше помогать другим"],
            ["г) Интересно как работает психика — хочу добавить это в практику"],
        ]},
        {"text": "Бывало ли что вы не знали как реагировать на клиента в сложный момент?", "options": [
            ["а) Да, и это меня беспокоит"],
            ["б) Да, действовал/а интуитивно — не всегда уверен/а"],
            ["в) Редко — у меня есть свои методы"],
            ["г) Часто — и не понимаю где граница моей компетенции"],
        ]},
        {"text": "Как вы отличаете что происходит с клиентом — от того что происходит с вами?", "options": [
            ["а) Обычно чувствую разницу"],
            ["б) Не всегда — иногда смешивается"],
            ["в) Это сложный вопрос — я над ним думаю"],
            ["г) Честно — не задумывался/ась об этом разграничении"],
        ]},
        {"text": "Что для вас сейчас важнее всего в профессиональном развитии?", "options": [
            ["а) Расширить инструментарий и методы"],
            ["б) Понять где заканчивается моя компетенция"],
            ["в) Углубить понимание психологических процессов"],
            ["г) Найти опору и устойчивость в работе с людьми"],
        ]},
        {"text": "Как вы восстанавливаетесь после интенсивной работы с клиентами?", "options": [
            ["а) Есть практики которые помогают"],
            ["б) Стараюсь, но не всегда получается"],
            ["в) Честно — не очень хорошо с этим справляюсь"],
            ["г) Не думал/а что это отдельная задача"],
        ]},
        {"text": "Есть ли клиент с которым вам было некомфортно — но вы продолжали работать?", "options": [
            ["а) Да, и я не всегда понимал/а почему"],
            ["б) Да, но умею с этим справляться"],
            ["в) Нет — я заканчиваю работу если чувствую дискомфорт"],
            ["г) Да, и это меня беспокоит"],
        ]},
        {"text": "Как вы видите связь между вашей работой и психологией?", "options": [
            ["а) Они дополняют друг друга — хочу интегрировать"],
            ["б) Психология даст мне то чего не хватает в моей практике"],
            ["в) Разные вещи — но клиенты часто смешивают"],
            ["г) Только начинаю об этом думать"],
        ]},
    ],

    4: [
        {"text": "Как давно у вас есть мысль стать психологом?", "options": [
            ["а) Недавно — что-то произошло что дало толчок"],
            ["б) Давно — но всё не решался/ась"],
            ["в) Это давняя мечта которую я откладываю"],
            ["г) Не уверен/а — просто интересно"],
        ]},
        {"text": "Что стоит за желанием стать психологом?", "options": [
            ["а) Хочу помогать людям — это главное"],
            ["б) Хочу понять себя — и это привело к интересу"],
            ["в) Кажется что у меня есть способности к этому"],
            ["г) Не до конца понимаю — но тянет"],
        ]},
        {"text": "Что вас останавливает прямо сейчас?", "options": [
            ["а) Не знаю с чего начать — много информации"],
            ["б) Сомневаюсь — подходит ли мне это"],
            ["в) Страшно менять привычный путь"],
            ["г) Финансовый вопрос и время"],
        ]},
        {"text": "Есть ли у вас опыт когда вы помогали кому-то в трудной ситуации?", "options": [
            ["а) Да, часто — люди приходят ко мне с проблемами"],
            ["б) Иногда — стараюсь помочь но не всегда знаю как"],
            ["в) Редко — не чувствую уверенности в таких ситуациях"],
            ["г) Да, и это меня очень наполняет"],
        ]},
        {"text": "Что вас привлекает в психологии больше всего?", "options": [
            ["а) Понимание как работает психика"],
            ["б) Возможность реально помогать людям"],
            ["в) Работа с отношениями и коммуникацией"],
            ["г) Возможность лучше понять себя"],
        ]},
        {"text": "Как вы относитесь к идее долгого обучения (3–7 лет)?", "options": [
            ["а) Готов/а — если это правильный путь"],
            ["б) Пугает — хочется понять точно что это моё"],
            ["в) Не знал/а что так долго — это меняет картину"],
            ["г) Нормально — важен результат"],
        ]},
        {"text": "Есть ли кто-то в вашем окружении кто поддерживает эту идею?", "options": [
            ["а) Да, и это придаёт уверенности"],
            ["б) Нет — скорее отговаривают"],
            ["в) Не говорил/а никому — это пока внутренний вопрос"],
            ["г) Смешанная реакция"],
        ]},
        {"text": "Что вы ищете прямо сейчас?", "options": [
            ["а) Понять — подходит ли мне эта профессия"],
            ["б) Найти первый шаг с чего начать"],
            ["в) Узнать больше о том как устроена профессия"],
            ["г) Почувствовать поддержку и ориентир"],
        ]},
    ],
}

# ─── ПРОМПТЫ CLAUDE ───────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    1: "Ты — ИИ-агент института PRIMA TA для практикующих психологов. Философия PRIMA: зрелость терапевта — это не сумма знаний, а способность удерживать себя в контакте с клиентом. Говори спокойно, точно, без давления. Язык гипотез.",
    2: "Ты — ИИ-агент института PRIMA TA для обучающихся психологов. Философия PRIMA: путь терапевта начинается с понимания себя. Говори тепло и поддерживающе. Язык гипотез.",
    3: "Ты — ИИ-агент института PRIMA TA для специалистов помогающих профессий. Уважай их опыт. Покажи как психологическое понимание углубит их практику. Язык гипотез.",
    4: "Ты — ИИ-агент института PRIMA TA для людей думающих о профессии психолога. Говори тепло, без давления. Создай пространство для размышления. Язык гипотез.",
}

MK_DESCRIPTIONS = {
    1: "Судя по вашим ответам, мастер-класс может помочь вам назвать то, что вы уже чувствуете в работе, но пока не можете сформулировать. Вы сможете увидеть — что именно происходит между вами и клиентом, и как ваше внутреннее состояние влияет на это поле.",
    2: "Судя по вашим ответам, мастер-класс может помочь вам понять — что на самом деле нужно, чтобы войти в практику не из тревоги, а из опоры.",
    3: "Судя по вашим ответам, мастер-класс может помочь вам увидеть — где заканчивается ваша компетенция и начинается то, что требует психологического мышления.",
    4: "Судя по вашим ответам, мастер-класс может помочь вам лучше понять — что на самом деле стоит за вашим интересом к профессии.",
}

COMMUNITY_DESCRIPTIONS = {
    1: "Если после мастер-класса вы почувствуете, что хотите продолжить — в PRIMA есть Сообщество практики. Это пространство, где терапевты развивают устойчивость через структурированную 12-месячную программу, живые встречи и работу в малых группах. Не курс — среда, в которой практика становится опорой.",
    2: "Если после мастер-класса вы почувствуете, что хотите продолжить — в PRIMA есть Сообщество практики. Это пространство для тех, кто учится или только входит в практику: структурированная программа, живые встречи и среда, в которой можно развиваться не в одиночку.",
    3: "Если после мастер-класса вы почувствуете, что хотите продолжить — в PRIMA есть Сообщество практики. Это пространство, где специалисты помогающих профессий углубляют понимание себя и развивают устойчивость в работе с людьми.",
    4: "Если после мастер-класса вы почувствуете, что хотите продолжить — в PRIMA есть возможность начать путь в профессию через обучение в методе транзактного анализа. Не быстро, но глубоко.",
}

TYPE_NAMES = {
    1: "практикующий психолог",
    2: "обучающийся психолог",
    3: "специалист помогающей профессии",
    4: "человек думающий о профессии психолога",
}

# ─── ГЕНЕРАЦИЯ РЕЗУЛЬТАТА ────────────────────────────────────────────────────

def generate_result(user_type: int, answers: list) -> tuple:
    answers_text = "\n\n".join([
        f"Вопрос {i+1}: \"{QUESTIONS[user_type][i]['text']}\"\nОтвет: \"{a}\""
        for i, a in enumerate(answers)
    ])

    prompt = f"""Участник: {TYPE_NAMES[user_type]}

Ответы:
{answers_text}

Напиши персональные наблюдения в пяти частях. Тон: спокойный, точный, уважительный. Обращайся на "вы". Не давай советов — только наблюдай и отражай. Язык гипотез.

ВАЖНО: каждая часть должна содержать реальный текст. Никогда не пиши просто заголовок без содержания.

ЧАСТЬ 1 — НАЗВАНИЕ: одна строка, максимум 7 слов. Начни строку с "##" и сразу пиши название. Пример: "## На пороге глубины"

ЧАСТЬ 2 — НАБЛЮДЕНИЯ: 2 абзаца по 2-3 предложения.
— Абзац 1: что возможно происходит в практике/пути прямо сейчас.
— Абзац 2: что может стоять за этим внутри.
Используй: "возможно", "похоже", "это может быть связано".
Начни строку с "###" и сразу пиши текст.

ЧАСТЬ 3 — ТЕКУЩАЯ ПОЗИЦИЯ: одно предложение. Обязательно начинается "Возможно, сейчас вы" + конкретное описание. Начни строку с "####". Пример: "#### Возможно, сейчас вы в точке где теория уже есть, а живой опоры в себе ещё нет"

ЧАСТЬ 4 — СЛЕДУЮЩИЙ ЭТАП: одно предложение. Обязательно начинается "Следующий этап —" + конкретный образ. Начни строку с "#####". Пример: "##### Следующий этап — научиться замечать себя в моменте контакта"

ЧАСТЬ 5 — ПОЛЬЗА МК: 2-3 предложения о том, чем конкретно этому человеку будет полезен мастер-класс PRIMA. Конкретно под его ситуацию. Начни строку с "######".
"""

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPTS[user_type],
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text

    def extract(pattern, txt):
        m = re.search(pattern, txt, re.DOTALL)
        return m.group(1).strip() if m else ""

    name        = extract(r'##(?!#)([^\n]+)', text)
    body        = extract(r'###(?!#)(.+?)(?=####)', text)
    current_pos = extract(r'####(?!#)([^\n]+)', text)
    next_step   = extract(r'#####(?!#)([^\n]+)', text)
    mk_personal = extract(r'######(?!#)(.+?)(?=$)', text)

    if not name:        name = "Наблюдения готовы"
    if not current_pos or current_pos.lower() in ["текущая позиция"]:
        current_pos = "Возможно, сейчас вы на этапе, когда что-то важное уже ощущается, но ещё не названо"
    if not next_step or next_step.lower() in ["следующий этап"]:
        next_step = "Следующий этап — остановиться и посмотреть на себя в практике честно"
    if not mk_personal:
        mk_personal = MK_DESCRIPTIONS[user_type]

    community_text = COMMUNITY_DESCRIPTIONS[user_type]

    result = f"""*{name}*

{body}

_Текущая позиция:_
_{current_pos}_

_Следующий этап:_
_{next_step}_

━━━━━━━━━━━━━━━━━━━━━━

*Мастер-класс PRIMA*
_«Что стоит за успешной практикой терапевта?»_

{mk_personal}

{community_text}"""

    return result, name

# ─── НАПОМИНАНИЯ ─────────────────────────────────────────────────────────────

remind_users = set()  # user_id тех кто хочет напоминания

async def send_reminder_1(app):
    """14:00 — за 3 часа"""
    for uid in remind_users:
        try:
            await app.bot.send_message(
                uid,
                "Добрый день.\n\nЧерез 3 часа начинается мастер-класс PRIMA «Что стоит за успешной практикой терапевта?»\n\nНачало в 17:00 по времени Астаны.\n\nДо встречи.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 Ссылка на мастер-класс", url=MK_LINK)
                ]])
            )
        except Exception as e:
            logging.error(f"Reminder 1 error for {uid}: {e}")

async def send_reminder_2(app):
    """17:00 — начало"""
    for uid in remind_users:
        try:
            await app.bot.send_message(
                uid,
                "Мастер-класс PRIMA начинается прямо сейчас.\n\nБудем рады вашему присутствию.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔗 Присоединиться", url=MK_LINK)
                ]])
            )
        except Exception as e:
            logging.error(f"Reminder 2 error for {uid}: {e}")

async def send_post_mk_survey(app):
    """19:00 — опрос после МК"""
    for uid in remind_users:
        try:
            await app.bot.send_message(
                uid,
                "Мастер-класс завершился.\n\nВы были сегодня на мастер-классе?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Да, был/а"], ["Не смог/ла прийти"]],
                    resize_keyboard=True, one_time_keyboard=True
                )
            )
        except Exception as e:
            logging.error(f"Post-MK survey error for {uid}: {e}")

# ─── HANDLERS — КВИЗ ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        INTRO_TEXT + "\n\n*" + TYPE_QUESTION + "*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(TYPE_OPTIONS, resize_keyboard=True, one_time_keyboard=True)
    )
    return SELECT_TYPE

async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "1." in text:   user_type = 1
    elif "2." in text: user_type = 2
    elif "3." in text: user_type = 3
    elif "4." in text: user_type = 4
    else:
        await update.message.reply_text("Пожалуйста, выберите один из вариантов.")
        return SELECT_TYPE

    context.user_data["type"] = user_type
    context.user_data["answers"] = []
    context.user_data["step"] = 0
    return await ask_question(update, context)

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_type = context.user_data["type"]
    step = context.user_data["step"]
    questions = QUESTIONS[user_type]

    if step >= len(questions):
        return await finish_quiz(update, context)

    q = questions[step]
    await update.message.reply_text(
        f"*Вопрос {step + 1} из {len(questions)}*\n\n{q['text']}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(q["options"], resize_keyboard=True, one_time_keyboard=True)
    )
    return Q1 + step

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"].append(update.message.text)
    context.user_data["step"] += 1
    return await ask_question(update, context)

async def finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Формирую наблюдения по вашим ответам...\n\nЭто займёт несколько секунд.",
        reply_markup=ReplyKeyboardRemove()
    )

    user_type = context.user_data["type"]
    answers   = context.user_data["answers"]

    try:
        result, result_name = generate_result(user_type, answers)
        context.user_data["result_name"] = result_name
        await update.message.reply_text(result, parse_mode="Markdown")

        # Сохраняем в Google Sheets
        save_quiz_result(update.effective_user, user_type, answers, result_name)

        # Переходим к диалогу после квиза
        await update.message.reply_text(
            "Вы уже зарегистрированы на мастер-класс «Что стоит за успешной практикой терапевта?»?",
            reply_markup=ReplyKeyboardMarkup(
                [["✓ Да, зарегистрирован/а"], ["Ещё нет"]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return ASK_REGISTERED

    except Exception as e:
        logging.error(f"Quiz finish error: {e}")
        await update.message.reply_text(
            "Что-то пошло не так. Попробуйте начать заново — /start",
            reply_markup=manager_keyboard()
        )
        return ConversationHandler.END

# ─── HANDLERS — ПОСЛЕ КВИЗА ──────────────────────────────────────────────────

async def ask_registered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Да" in text:
        await update.message.reply_text(
            "Хотите, чтобы я напомнил вам о мастер-классе за 3 часа до начала?",
            reply_markup=ReplyKeyboardMarkup(
                [["Да, напомни"], ["Не нужно"]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        context.user_data["mk_registered"] = "да"
        return ASK_REMINDER
    else:
        context.user_data["mk_registered"] = "нет"
        save_mk_data(update.effective_user, {
            "registered": "нет",
            "reminder": "—",
        })
        await update.message.reply_text(
            "Если захотите присоединиться — мастер-класс пройдёт 3 апреля. Мы рады всем, кто чувствует отклик.\n\nЕсли появятся вопросы — наш менеджер всегда рядом.",
            reply_markup=manager_keyboard()
        )
        return ConversationHandler.END

async def ask_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Да" in text:
        remind_users.add(update.effective_user.id)
        context.user_data["mk_reminder"] = "да"
        save_mk_data(update.effective_user, {
            "registered": context.user_data.get("mk_registered", "—"),
            "reminder": "да",
        })
        await update.message.reply_text(
            "Договорились. Напомню вам 3 апреля в 14:00 по времени Астаны.",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        context.user_data["mk_reminder"] = "нет"
        save_mk_data(update.effective_user, {
            "registered": context.user_data.get("mk_registered", "—"),
            "reminder": "нет",
        })
        await update.message.reply_text(
            "Понял. Будем рады видеть вас на мастер-классе. Если появятся вопросы — наш менеджер всегда рядом.",
            reply_markup=manager_keyboard()
        )
    return ConversationHandler.END

# ─── HANDLERS — ОПРОС ПОСЛЕ МК ───────────────────────────────────────────────

async def post_mk_attended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["mk_attended"] = text

    if "Да" in text:
        await update.message.reply_text(
            "Как вам мастер-класс в целом?",
            reply_markup=ReplyKeyboardMarkup(
                [["Очень понравился"], ["Понравился"],
                 ["Нейтрально"], ["Ожидал/а другого"]],
                resize_keyboard=True, one_time_keyboard=True
            )
        )
        return POST_MK_Q1
    else:
        save_mk_data(update.effective_user, {
            "registered": "да", "reminder": "да",
            "attended": "нет",
        })
        await update.message.reply_text(
            "Понимаем — бывает. Запись мастер-класса будет опубликована в Instagram Рахимы Жолтановны.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Instagram @rakhima.kuandykova", url=INSTAGRAM_RJ)],
                [InlineKeyboardButton("💬 Написать менеджеру", url=MANAGER_URL)],
            ])
        )
        return ConversationHandler.END

async def post_mk_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mk_rating"] = update.message.text
    await update.message.reply_text(
        "Что было наиболее ценным для вас?",
        reply_markup=ReplyKeyboardMarkup(
            [["Живая работа — увидел/а метод в действии"],
             ["Программа сообщества — стало яснее зачем это"],
             ["Разбор Рахимы Жолтановны — точно попал/а в моё"],
             ["Другое"]],
            resize_keyboard=True, one_time_keyboard=True
        )
    )
    return POST_MK_Q2

async def post_mk_q2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mk_valuable"] = update.message.text
    await update.message.reply_text(
        "После мастер-класса — есть ли интерес к Сообществу практики PRIMA?",
        reply_markup=ReplyKeyboardMarkup(
            [["Да, хочу узнать подробнее"],
             ["Думаю об этом"],
             ["Пока нет"]],
            resize_keyboard=True, one_time_keyboard=True
        )
    )
    return POST_MK_Q3

async def post_mk_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["community_interest"] = text

    if "Пока нет" in text:
        await update.message.reply_text(
            "Есть ли что-то, что вы хотели бы передать команде PRIMA?",
            reply_markup=ReplyKeyboardRemove()
        )
        return POST_MK_FREE
    else:
        # Уведомляем менеджера
        try:
            user = update.effective_user
            manager_msg = (
                f"🔔 Новый интерес к сообществу\n\n"
                f"Пользователь: {user.full_name}\n"
                f"Username: @{user.username or '—'}\n"
                f"Тип аудитории: {context.user_data.get('type', '—')}\n"
                f"Оценка МК: {context.user_data.get('mk_rating', '—')}\n"
                f"Что ценного: {context.user_data.get('mk_valuable', '—')}\n"
                f"Интерес к сообществу: {text}\n\n"
                f"Свяжитесь с ним/ней."
            )
            # Отправить менеджеру (нужно узнать chat_id @Prima_TA)
            # await app.bot.send_message(MANAGER_CHAT_ID, manager_msg)
        except Exception as e:
            logging.error(f"Manager notify error: {e}")

        context.user_data["sent_to_manager"] = "да"
        await update.message.reply_text(
            "Рады это слышать. С вами свяжется наш менеджер отдела заботы — ответит на все вопросы и расскажет подробнее о сообществе.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Написать менеджеру", url=MANAGER_URL)
            ]])
        )
        await update.message.reply_text(
            "Есть ли что-то, что вы хотели бы передать команде PRIMA?",
            reply_markup=ReplyKeyboardRemove()
        )
        return POST_MK_FREE

async def post_mk_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["free_feedback"] = update.message.text

    save_mk_data(update.effective_user, {
        "registered": "да",
        "reminder": "да",
        "attended": context.user_data.get("mk_attended", "—"),
        "mk_rating": context.user_data.get("mk_rating", "—"),
        "mk_valuable": context.user_data.get("mk_valuable", "—"),
        "community_interest": context.user_data.get("community_interest", "—"),
        "free_feedback": update.message.text,
        "sent_to_manager": context.user_data.get("sent_to_manager", "нет"),
    })

    await update.message.reply_text(
        "Благодарим за обратную связь. Это важно для нас.\n\nДо следующих встреч.",
        reply_markup=manager_keyboard()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Опросник прерван. Чтобы начать заново — /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_TYPE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, select_type)],
            **{Q1 + i:        [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)]
               for i in range(8)},
            ASK_REGISTERED:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_registered)],
            ASK_REMINDER:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_reminder)],
            POST_MK_ATTENDED: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_mk_attended)],
            POST_MK_Q1:       [MessageHandler(filters.TEXT & ~filters.COMMAND, post_mk_q1)],
            POST_MK_Q2:       [MessageHandler(filters.TEXT & ~filters.COMMAND, post_mk_q2)],
            POST_MK_Q3:       [MessageHandler(filters.TEXT & ~filters.COMMAND, post_mk_q3)],
            POST_MK_FREE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, post_mk_free)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)

    # Планировщик напоминаний — 3 апреля по Астане (UTC+5)
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    scheduler.add_job(send_reminder_1,   "date", run_date="2026-04-03 14:00:00", args=[app])
    scheduler.add_job(send_reminder_2,   "date", run_date="2026-04-03 17:00:00", args=[app])
    scheduler.add_job(send_post_mk_survey,"date", run_date="2026-04-03 19:00:00", args=[app])
    scheduler.start()

    print("PRIMA Bot запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
