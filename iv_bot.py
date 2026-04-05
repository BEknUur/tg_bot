"""
PRIMA TA · Интервизионный бот
Опросник для формирования ИВ-групп

Установка:
    pip install python-telegram-bot gspread google-auth python-dotenv

Запуск:
    python iv_bot.py
"""

import logging
import os
from datetime import datetime
from collections import Counter

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("IV_BOT_TOKEN")
GOOGLE_SHEET_ID  = os.getenv("IV_SHEET_ID")
GOOGLE_CREDS     = os.getenv("IV_CREDENTIALS_FILE", "iv_credentials.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

(
    COLLECT_NAME,
    COLLECT_PHONE,
    COLLECT_CONTACT,
    JOINES,
    ORG,
    PROFILE,
) = range(6)

# ─── ДАННЫЕ ОПРОСНИКОВ ───────────────────────────────────────────────────────

JOINES_QUESTIONS = [
    "Я думаю, что большинство людей беспечны в том, чем они занимаются.",
    "Люди говорят мне, что я тихий.",
    "Мне более комфортно заниматься делами, чем общаться с людьми.",
    "Я убегаю, когда всё идёт плохо.",
    "Во время конфликтов я чувствую, что что бы я ни сделал — будет только хуже.",
    "Если люди недовольны мной, я чувствую себя задетым и смущённым.",
    "Когда я с другими людьми, мне кажется, что я должен поступаться своими желаниями.",
    "Я люблю делиться своими чувствами.",
    "Часто я считаю необходимым отстаивать свою правоту.",
    "Когда у меня важные проекты, я задерживаюсь дольше коллег, чтобы сделать всё правильно.",
    "Я хитрый, как лиса.",
    "Меня злит безответственность.",
    "Я склонен не делать перерывы, а сразу переходить к следующему делу.",
    "Мне сложно принимать решения.",
    "Мои чувства написаны у меня на лице.",
    "Мне нравится рисковать.",
    "Меня обвиняют в том, что я принимаю всё слишком близко к сердцу.",
    "Я склонен сомневаться во всём, пока нет доказательств.",
    "Мне комфортнее быть одному, чем среди людей.",
    "Я люблю нарушать правила.",
    "Я устаю, если слишком долго нахожусь среди людей.",
    "Мной движет возбуждение.",
    "Люди часто разбивают моё сердце.",
    "Друзья говорят мне, что я часто флиртую.",
    "Мне нравится говорить людям, что я думаю.",
    "Мне говорят, что я перфекционист.",
    "Я часто проверяю, всё ли выключил.",
    "Мне нравится уединение.",
    "Многие вещи расстраивают меня.",
    "Я верю: если хочу, чтобы что-то было сделано правильно, — надо сделать самому.",
    "Я откладываю развлечения, пока работа не будет окончена.",
    "Мне нравится развлекаться среди людей.",
    "Когда другие развлекаются, я работаю.",
    "Я подозрительно отношусь к мотивам других людей.",
    "Люди считают меня слишком эмоциональным.",
    "Люблю, когда мне всё сходит с рук.",
]

JOINES_SCALES = {
    "Ответственный работоголик": [9, 12, 25, 26, 30, 32],
    "Блестящий скептик":         [0,  8, 11, 17, 29, 33],
    "Игривый сопротивленец":     [4,  5, 13, 16, 22, 28],
    "Очаровывающий манипулятор": [3, 10, 15, 19, 21, 35],
    "Творческий мечтатель":      [1,  2,  6, 18, 20, 27],
    "Сверхреагирующий энтузиаст":[7, 14, 23, 24, 31, 34],
}

SCALE_CODES = {
    "Ответственный работоголик": "OCR",
    "Блестящий скептик":         "PAR",
    "Игривый сопротивленец":     "PAS",
    "Очаровывающий манипулятор": "ANT",
    "Творческий мечтатель":      "SHZ",
    "Сверхреагирующий энтузиаст":"IST",
}

ORG_QUESTIONS = [
    {
        "text": "Близкий человек не отвечает на сообщение несколько часов. Что происходит внутри?",
        "options": [
            ["А) Нарастает тревога — прокручиваю, всё ли в порядке, не обидел(а) ли я его"],
            ["Б) Немного задевает — как будто я недостаточно важен(на), чтобы ответить сразу"],
            ["В) Ничего особенного — даже немного рад(а) паузе"],
        ]
    },
    {
        "text": "Коллега на разборе случая мягко указывает на ошибку в вашей работе. Что вы чувствуете в первый момент?",
        "options": [
            ["А) Беспокойство — боюсь, что теперь хуже думают обо мне как о человеке"],
            ["Б) Укол изнутри — хочется объяснить, почему я принял(а) именно такое решение"],
            ["В) Желание закрыться — кажется, что в мою территорию вторглись"],
        ]
    },
    {
        "text": "После интенсивного двухдневного тренинга вам предлагают сразу поехать в компанию. Вы скорее всего:",
        "options": [
            ["А) Согласитесь — в компании лучше, чем оставаться наедине с впечатлениями"],
            ["Б) Пойдёте, если там будут люди, чьё мнение для вас важно"],
            ["В) Откажетесь — нужно время побыть одному и переварить"],
        ]
    },
    {
        "text": "Терапевт берёт отпуск на три недели. Как вы это переживаете (или переживали бы)?",
        "options": [
            ["А) Трудно — ощущение, что теряю опору, нужно специально держаться"],
            ["Б) Немного обидно — как будто моя работа не настолько важна, чтобы перенести"],
            ["В) С облегчением — пауза даёт пространство"],
        ]
    },
    {
        "text": "Вы провели сессию, которой довольны. Что важнее всего в этот момент?",
        "options": [
            ["А) Чтобы клиент тоже почувствовал что-то важное — наш контакт стал глубже"],
            ["Б) Ощущение, что я сработал(а) профессионально и точно"],
            ["В) Спокойствие от того, что всё прошло в рамках — без лишних вторжений"],
        ]
    },
    {
        "text": "В группе кто-то говорит очень лично и со слезами. Ваша первая реакция:",
        "options": [
            ["А) Включаюсь эмоционально — хочется быть рядом, поддержать"],
            ["Б) Наблюдаю — интересно, что за этим стоит, оцениваю ситуацию"],
            ["В) Внутренне немного отстраняюсь — интенсивность давит"],
        ]
    },
    {
        "text": "Что для вас субъективно хуже — оказаться совсем одному на несколько дней или услышать обидную оценку от важного человека?",
        "options": [
            ["А) Одиночество — оно ощущается как что-то невыносимое"],
            ["Б) Обидная оценка — она задевает что-то глубокое внутри"],
            ["В) Оба варианта умеренны — одиночество даже предпочтительнее"],
        ]
    },
    {
        "text": "Супервизор очень тепло и подробно разбирает вашу работу, задаёт много личных вопросов. Вы:",
        "options": [
            ["А) Ценю это — чувствую, что меня видят и принимают"],
            ["Б) Приятно, но слежу — важно, чтобы оценка была справедливой"],
            ["В) Немного напряжён(а) — столько внимания ощущается как слишком много"],
        ]
    },
    {
        "text": "Конфликт с коллегой завершился. Что остаётся дольше всего?",
        "options": [
            ["А) Беспокойство — всё ли в порядке с отношениями, нет ли обиды"],
            ["Б) Прокрутка — был ли я прав, как меня восприняли"],
            ["В) Усталость от самого факта столкновения — хочется тишины"],
        ]
    },
    {
        "text": "Клиент внезапно завершает работу без объяснений. Что первое?",
        "options": [
            ["А) Тревога и растерянность — что случилось, всё ли я сделал(а) правильно"],
            ["Б) Задетость — как будто моя работа оказалась недостаточно ценной"],
            ["В) Принятие с лёгким облегчением — пространство освободилось"],
        ]
    },
    {
        "text": "На групповом обучении вас просят поделиться чем-то личным. Вы:",
        "options": [
            ["А) Делитесь охотно — это создаёт близость, которая важна"],
            ["Б) Делитесь избирательно — важно выглядеть цельно и профессионально"],
            ["В) Чувствуете сопротивление — личное кажется своим, не для группы"],
        ]
    },
    {
        "text": "Какое состояние вам знакомо лучше всего?",
        "options": [
            ["А) Колебания между «всё хорошо» и «всё рушится» в зависимости от отношений"],
            ["Б) Ощущение, что нужно постоянно держать уровень — расслабляться опасно"],
            ["В) Комфорт в своём внутреннем мире, который хочется защищать от вторжений"],
        ]
    },
]

PROFILE_QUESTIONS = [
    {
        "key": "specialization",
        "text": "С кем вы преимущественно работаете (или планируете)?",
        "options": [
            ["Взрослые (индивидуально)"],
            ["Дети и подростки"],
            ["Пары"],
            ["Организации / группы"],
            ["Смешанно / пока не определился"],
        ]
    },
    {
        "key": "years_in_practice",
        "text": "Сколько лет вы в профессии?",
        "options": [
            ["Менее 1 года"],
            ["1–3 года"],
            ["3–7 лет"],
            ["7–15 лет"],
            ["Более 15 лет"],
        ]
    },
    {
        "key": "ta_stage",
        "text": "Ваш этап в обучении ТА (или другом направлении)?",
        "options": [
            ["Не в ТА-обучении, другое направление"],
            ["Знакомлюсь с ТА (до 101)"],
            ["ТА 101"],
            ["ТА 202"],
            ["Готовлюсь к CTA / CTA / TSTA"],
        ]
    },
    {
        "key": "motivation",
        "text": "Что для вас главное в интервизионной группе?",
        "options": [
            ["Разбор клинических случаев"],
            ["Работа с переносом и контрпереносом"],
            ["Групповая динамика и процессы"],
            ["Техники и инструменты ТА"],
            ["Профессиональная поддержка и сообщество"],
        ]
    },
    {
        "key": "timezone",
        "text": "Ваш часовой пояс? (для планирования встреч группы)",
        "options": [
            ["UTC+1–2 (Европа)"],
            ["UTC+2–3 (Киев / Москва)"],
            ["UTC+4–5 (Баку / Екатеринбург)"],
            ["UTC+6–7 (Алматы / Новосибирск)"],
            ["UTC+8–10 (Иркутск / Владивосток)"],
            ["Другой"],
        ]
    },
]

# ─── ИНТЕРПРЕТАЦИИ ───────────────────────────────────────────────────────────

ADAPTATION_NAMES = {
    "OCR": "Ответственный работоголик",
    "PAR": "Блестящий скептик",
    "PAS": "Игривый сопротивленец",
    "ANT": "Очаровывающий манипулятор",
    "SHZ": "Творческий мечтатель",
    "IST": "Сверхреагирующий энтузиаст",
}

# Интерпретации для основных сочетаний адаптация + организация
INTERPRETATIONS = {
    ("OCR", "Шиз"): (
        "Это сочетание — работоголик с шизоидной организацией — означает человека, "
        "который очень много делает и держит высокую планку, но энергию черпает в одиночестве "
        "и воспринимает излишнюю близость как вторжение. Профессионально это часто выглядит "
        "как очень компетентный, структурированный специалист, которому важно держать "
        "дистанцию в контакте."
    ),
    ("OCR", "Нарц"): (
        "Работоголик с нарциссической организацией — это специалист, для которого качество "
        "работы неотделимо от чувства собственной ценности. Высокий стандарт — и защита, "
        "и источник смысла. Критика воспринимается остро, но именно это держит планку."
    ),
    ("OCR", "ПРЛ"): (
        "Работоголик с пограничной организацией — человек, который использует дела и "
        "высокие стандарты как способ регулировать внутреннее напряжение. Пока всё под "
        "контролем — тревога отступает. Важно иметь стабильную опору рядом."
    ),
    ("PAR", "Шиз"): (
        "Скептик с шизоидной организацией — аналитик, который наблюдает со стороны и "
        "не доверяет легко. Это сочетание даёт остроту мышления и глубину анализа, "
        "но контакт в группе требует времени и предсказуемости."
    ),
    ("PAR", "Нарц"): (
        "Скептик с нарциссической организацией — человек с высокими стандартами "
        "и острым взглядом на несоответствия. В группе может быть ценным критическим "
        "голосом, если удастся создать достаточно безопасную атмосферу."
    ),
    ("PAR", "ПРЛ"): (
        "Скептицизм как защита в сочетании с пограничной организацией — это часто "
        "означает человека, который очень чувствителен к нарушениям договорённостей "
        "и ждёт подвоха. Доверие строится медленно, но прочно."
    ),
    ("PAS", "Шиз"): (
        "Сопротивленец с шизоидной организацией — человек, который избегает конфликта "
        "через дистанцию и пассивность. В группе может быть тихим и ненавязчивым, "
        "но его голос важно специально приглашать."
    ),
    ("PAS", "Нарц"): (
        "Пассивное сопротивление с нарциссической организацией — это нередко "
        "скрытая борьба за признание. Человек не заявляет о потребностях напрямую, "
        "но остро переживает, когда их не замечают."
    ),
    ("PAS", "ПРЛ"): (
        "Сопротивление как адаптация с пограничной организацией — это сочетание, "
        "при котором человек может одновременно очень нуждаться в контакте и "
        "противиться ему. Группа может стать местом, где это постепенно меняется."
    ),
    ("ANT", "Шиз"): (
        "Манипулятор с шизоидной организацией — человек, который умеет производить "
        "нужное впечатление, оставаясь при этом эмоционально недоступным. "
        "В группе ценен как стратег, важно приглашать к подлинному контакту."
    ),
    ("ANT", "Нарц"): (
        "Антисоциальная адаптация с нарциссической организацией — это сочетание "
        "даёт человека с большой энергией, харизмой и склонностью к риску. "
        "Группа будет живой — и потребует устойчивых границ."
    ),
    ("ANT", "ПРЛ"): (
        "Манипулятивная адаптация с пограничной организацией — это часто "
        "способ справляться с интенсивной внутренней нестабильностью через "
        "контроль внешней среды. Группа может стать местом большой трансформации."
    ),
    ("SHZ", "Шиз"): (
        "Мечтатель с шизоидной организацией — человек с богатым внутренним миром, "
        "которому нужно много пространства. Глубокий, думающий, творческий — "
        "и нуждающийся в очень постепенном темпе сближения в группе."
    ),
    ("SHZ", "Нарц"): (
        "Шизоидная адаптация с нарциссической организацией — человек, который "
        "защищает свою уникальность и глубину от обесценивания. "
        "В группе важно, чтобы его взгляд был услышан и признан."
    ),
    ("SHZ", "ПРЛ"): (
        "Мечтатель с пограничной организацией — интроверт с интенсивным "
        "внутренним миром и острой чувствительностью к отношениям. "
        "Уединение и связь важны одновременно — и это само по себе тема для работы."
    ),
    ("IST", "Шиз"): (
        "Энтузиаст с шизоидной организацией — это на первый взгляд неочевидное "
        "сочетание: живой снаружи, закрытый внутри. Эмоциональность — скорее "
        "адаптация, чем отражение реального состояния. Группа может помочь "
        "найти контакт с настоящим."
    ),
    ("IST", "Нарц"): (
        "Энтузиаст с нарциссической организацией — яркий, вовлечённый, "
        "нуждающийся в отклике. Очень продуктивен в группе, пока чувствует "
        "признание. Важно замечать и называть его вклад."
    ),
    ("IST", "ПРЛ"): (
        "Сверхреагирующий энтузиаст с пограничной организацией — человек "
        "с большой эмоциональной амплитудой и острой чувствительностью к "
        "качеству отношений. В группе будет очень живым — и важно, чтобы "
        "ведущий умел удерживать этот уровень интенсивности."
    ),
}

ADAPTATION_DESCRIPTIONS = {
    "OCR": "Вы склонны брать на себя ответственность, держать высокую планку и доводить дела до конца — даже ценой личного времени.",
    "PAR": "Вы внимательны к деталям, критически мыслите и не принимаете вещи на веру — это ценный аналитический ресурс.",
    "PAS": "Вы чувствительны к давлению и несправедливости, склонны сопротивляться — иногда косвенно. За этим часто стоит много невысказанного.",
    "ANT": "Вам свойственна гибкость, находчивость и готовность к риску. Вы умеете ориентироваться в сложных ситуациях.",
    "SHZ": "У вас богатый внутренний мир, вы ценёте пространство и тишину. Глубина — ваша природная территория.",
    "IST": "Вы эмоционально живой, легко входите в контакт и умеете создавать тепло. Реакции быстрые и яркие.",
}

ORG_DESCRIPTIONS = {
    "ПРЛ":       "в фокусе — контакт и связь с другими.",
    "Нарц":      "в фокусе — самооценка и ощущение значимости.",
    "Шиз":       "в фокусе — автономия и личное пространство.",
    "Смешанная": "несколько стилей выражены примерно одинаково.",
}


def build_interpretation(top_code: str, org_type: str) -> str:
    key = (top_code, org_type)
    if key in INTERPRETATIONS:
        return INTERPRETATIONS[key]
    # Fallback — общая интерпретация
    adapt_desc = ADAPTATION_DESCRIPTIONS.get(top_code, "")
    org_desc = ORG_DESCRIPTIONS.get(org_type, "")
    return f"{adapt_desc} В стиле реагирования {org_desc}"


# ─── EXCEL ───────────────────────────────────────────────────────────────────

HEADERS = [
    "telegram_id", "username", "name", "phone", "contact_method",
    "specialization", "years_in_practice", "ta_stage", "motivation", "timezone",
    "OCR", "PAR", "PAS", "ANT", "SHZ", "IST", "top_adaptation",
    "org_PRL", "org_Narc", "org_Shiz", "org_type",
    "completed_at",
]


def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    if sheet.row_count == 0 or not sheet.cell(1, 1).value:
        sheet.append_row(HEADERS)
    return sheet


def save_to_sheet(data: dict):
    sheet = get_sheet()
    all_rows = sheet.get_all_values()
    row = [str(data.get(h, "")) for h in HEADERS]
    tid = str(data.get("telegram_id", ""))
    for i, r in enumerate(all_rows[1:], start=2):
        if r and str(r[0]) == tid:
            sheet.update(f"A{i}", [row])
            return
    sheet.append_row(row)


# ─── ПОДСЧЁТ РЕЗУЛЬТАТОВ ─────────────────────────────────────────────────────

def calc_joines(answers: list[int]) -> tuple[dict, str]:
    scores = {}
    for name, indices in JOINES_SCALES.items():
        code = SCALE_CODES[name]
        scores[code] = sum(answers[i] for i in indices)
    top = max(scores, key=scores.get)
    return scores, top


def calc_org(org_answers: list[str]) -> tuple[dict, str]:
    counts = Counter(org_answers)
    org_scores = {
        "org_PRL":  counts.get("А", 0),
        "org_Narc": counts.get("Б", 0),
        "org_Shiz": counts.get("В", 0),
    }
    sorted_c = counts.most_common()
    if len(sorted_c) >= 2 and sorted_c[0][1] - sorted_c[1][1] <= 2:
        org_type = "Смешанная"
    else:
        top_letter = sorted_c[0][0] if sorted_c else "?"
        mapping = {"А": "ПРЛ", "Б": "Нарц", "В": "Шиз"}
        org_type = mapping.get(top_letter, "Неясно")
    return org_scores, org_type


def build_results(ud: dict) -> str:
    scores = ud.get("joines_scores", {})
    top = ud.get("top_adaptation", "")
    org_type = ud.get("org_type", "")
    name = ud.get("name", "").split()[0]

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    bars = ""
    for code, score in sorted_scores:
        bar = "█" * score + "░" * (6 - score)
        marker = " ◀" if code == top else ""
        bars += f"  {bar} {score}/6  {ADAPTATION_NAMES.get(code, code)}{marker}\n"

    interpretation = build_interpretation(top, org_type)
    org_desc = ORG_DESCRIPTIONS.get(org_type, "")

    return (
        f"✨ *{name}, вот ваш профиль*\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Адаптации по Джойнсу*\n\n"
        f"{bars}\n"
        f"🔑 Доминирующая: *{ADAPTATION_NAMES.get(top, top)}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🧭 *Стиль реагирования:* {org_type}\n"
        f"_{org_desc}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *Что это значит вместе:*\n"
        f"{interpretation}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Эти данные помогут нам подобрать для вас наиболее подходящую "
        f"интервизионную группу.\n\n"
        f"📞 Координатор Отдела Заботы свяжется с вами в ближайшее время "
        f"и сообщит, в какую группу вы зачислены.\n\n"
        f"Если в течение *24 часов* с вами не связались — напишите сами:\n"
        f"*+7 778 440 98 82*\n\n"
        f"Рады, что вы с нами! 🙌"
    )


# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "*PRIMA TA · Интервизионные группы*\n\n"
        "Добрый день!\n\n"
        "Этот опросник поможет нам подобрать для вас подходящую интервизионную группу.\n\n"
        "Вас ждут три блока:\n"
        "1️⃣ Опросник адаптаций Джойнса (36 утверждений — да/нет)\n"
        "2️⃣ Опросник стиля реагирования (12 ситуативных вопросов)\n"
        "3️⃣ Анкета профессионального профиля (5 вопросов)\n\n"
        "Всего около 10 минут.\n\n"
        "Начнём — как вас зовут? *(имя и фамилия)*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return COLLECT_NAME


async def collect_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Укажите ваш номер телефона\n_(WhatsApp или Telegram)_",
        parse_mode="Markdown"
    )
    return COLLECT_PHONE


async def collect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text(
        "Где вам удобнее получить сообщение от координатора?",
        reply_markup=ReplyKeyboardMarkup(
            [["Telegram"], ["WhatsApp"]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return COLLECT_CONTACT


async def collect_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["contact_method"] = update.message.text.strip()
    context.user_data["joines_answers"] = []
    context.user_data["joines_step"] = 0
    name = context.user_data["name"].split()[0]
    await update.message.reply_text(
        f"Отлично, {name}!\n\n"
        f"*Блок 1 из 3 — Опросник адаптаций*\n"
        f"36 утверждений. На каждое отвечайте «Да» или «Нет».",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return await ask_joines(update, context)


async def ask_joines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["joines_step"]
    if step >= len(JOINES_QUESTIONS):
        return await finish_joines(update, context)
    progress = f"[{step + 1}/{len(JOINES_QUESTIONS)}]"
    await update.message.reply_text(
        f"{progress}\n\n{JOINES_QUESTIONS[step]}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Да"], ["❌ Нет"]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return JOINES


async def handle_joines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Да" in text:
        ans = 1
    elif "Нет" in text:
        ans = 0
    else:
        await update.message.reply_text("Пожалуйста, выберите Да или Нет.")
        return JOINES
    context.user_data["joines_answers"].append(ans)
    context.user_data["joines_step"] += 1
    return await ask_joines(update, context)


async def finish_joines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores, top = calc_joines(context.user_data["joines_answers"])
    context.user_data["joines_scores"] = scores
    context.user_data["top_adaptation"] = top
    context.user_data["org_answers"] = []
    context.user_data["org_step"] = 0
    await update.message.reply_text(
        "✅ *Первый блок завершён!*\n\n"
        "*Блок 2 из 3 — Стиль реагирования*\n"
        "12 ситуативных вопросов. Выбирайте вариант, который ближе всего к вашей реакции.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return await ask_org(update, context)


async def ask_org(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["org_step"]
    if step >= len(ORG_QUESTIONS):
        return await finish_org(update, context)
    q = ORG_QUESTIONS[step]
    progress = f"[{step + 1}/{len(ORG_QUESTIONS)}]"
    await update.message.reply_text(
        f"{progress}\n\n{q['text']}",
        reply_markup=ReplyKeyboardMarkup(
            q["options"],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return ORG


async def handle_org(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("А"):
        ans = "А"
    elif text.startswith("Б"):
        ans = "Б"
    elif text.startswith("В"):
        ans = "В"
    else:
        await update.message.reply_text("Пожалуйста, выберите один из вариантов.")
        return ORG
    context.user_data["org_answers"].append(ans)
    context.user_data["org_step"] += 1
    return await ask_org(update, context)


async def finish_org(update: Update, context: ContextTypes.DEFAULT_TYPE):
    org_scores, org_type = calc_org(context.user_data["org_answers"])
    context.user_data["org_scores"] = org_scores
    context.user_data["org_type"] = org_type
    context.user_data["profile"] = {}
    context.user_data["profile_step"] = 0
    await update.message.reply_text(
        "✅ *Второй блок завершён!*\n\n"
        "*Блок 3 из 3 — Профессиональный профиль*\n"
        "5 вопросов о вашем опыте и предпочтениях.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return await ask_profile(update, context)


async def ask_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["profile_step"]
    if step >= len(PROFILE_QUESTIONS):
        return await finish_all(update, context)
    q = PROFILE_QUESTIONS[step]
    progress = f"[{step + 1}/{len(PROFILE_QUESTIONS)}]"
    await update.message.reply_text(
        f"{progress}\n\n{q['text']}",
        reply_markup=ReplyKeyboardMarkup(
            q["options"],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return PROFILE


async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["profile_step"]
    q = PROFILE_QUESTIONS[step]
    context.user_data["profile"][q["key"]] = update.message.text.strip()
    context.user_data["profile_step"] += 1
    return await ask_profile(update, context)


async def finish_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    profile = ud.get("profile", {})
    scores = ud.get("joines_scores", {})
    org_scores = ud.get("org_scores", {})

    record = {
        "telegram_id": update.effective_user.id,
        "username":    update.effective_user.username or "",
        "name":        ud.get("name", ""),
        "phone":       ud.get("phone", ""),
        "contact_method": ud.get("contact_method", ""),
        **profile,
        **scores,
        "top_adaptation": ud.get("top_adaptation", ""),
        **org_scores,
        "org_type":    ud.get("org_type", ""),
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    try:
        save_to_sheet(record)
    except Exception as e:
        logging.error(f"Excel save error: {e}")

    results_text = build_results(ud)
    await update.message.reply_text(
        results_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Опросник прерван. Чтобы начать заново — /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            COLLECT_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name)],
            COLLECT_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_phone)],
            COLLECT_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_contact)],
            JOINES:          [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_joines)],
            ORG:             [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_org)],
            PROFILE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    print("ИВ-бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
