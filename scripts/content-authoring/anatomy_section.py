# ==================== АНАТОМИЯ (В РАЗРАБОТКЕ, ПОКА ДОСТУПНО ТОЛЬКО АДМИНАМ) ====================
ANATOMY_PUBLIC = False  # когда раздел будет готов для всех — переключить на True

ANATOMY_FLASH_SESSION_SIZE = 10
ANATOMY_MATCH_SESSION_SIZE = 10

ANATOMY_FLASH_SESSIONS: dict[int, dict] = {}
ANATOMY_MATCH_SESSIONS: dict[int, dict] = {}

def anatomy_access_ok(user_id: int) -> bool:
    return ANATOMY_PUBLIC or is_admin(user_id)

def get_anatomy_topic_data(topic_key: str):
    return ANATOMY.get("osteology", {}).get("topics", {}).get(topic_key)

def get_anatomy_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🦴 Остеология", callback_data="anatomy_osteology")
    builder.row(InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))
    return builder.as_markup()

def get_anatomy_osteology_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💀 Череп", callback_data="anatomy_topic:skull")
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="anatomy_menu"))
    return builder.as_markup()

def get_anatomy_topic_keyboard(topic_key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Материал", callback_data=f"anatomy_material:{topic_key}:0")
    builder.button(text="🎴 Флэш-карточки", callback_data=f"anatomy_flash_start:{topic_key}")
    builder.button(text="🔗 Сопоставление", callback_data=f"anatomy_match_start:{topic_key}")
    builder.button(text="🧠 Мнемоники", callback_data=f"anatomy_mnemonics:{topic_key}:0")
    builder.button(text="🖼 Найди на картинке", callback_data=f"anatomy_picture:{topic_key}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="anatomy_osteology"))
    return builder.as_markup()

# ---- Материал ----
def get_anatomy_material_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"anatomy_material:{topic_key}:{idx-1}"))
    if idx < len(material) - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"anatomy_material:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="📋 Список тем", callback_data=f"anatomy_material_list:{topic_key}"))
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_material_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    material = topic["material"]
    m = material[idx]
    return f"📖 <b>{m['title']}</b>\n{DIVIDER}\n\n{m['content']}\n\n{DIVIDER}\n{idx + 1}/{len(material)}"

def get_anatomy_material_list_keyboard(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    builder = InlineKeyboardBuilder()
    for i, m in enumerate(topic["material"]):
        builder.button(text=f"{i + 1}. {m['title']}", callback_data=f"anatomy_material:{topic_key}:{i}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

# ---- Флэш-карточки ----
def start_anatomy_flash_session(user_id: int, topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    pool = list(range(len(topic["flashcards"])))
    size = min(ANATOMY_FLASH_SESSION_SIZE, len(pool))
    ANATOMY_FLASH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "cards": random.sample(pool, size),
        "index": 0,
        "know": 0,
        "dont_know": 0,
    }

def get_anatomy_flash_question_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🙈 Показать ответ", callback_data="anatomy_flash_show_answer")
    builder.button(text="🛑 Закончить", callback_data="anatomy_flash_stop")
    builder.adjust(1)
    return builder.as_markup()

def get_anatomy_flash_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data="anatomy_flash_know")
    builder.button(text="❌ Не знаю", callback_data="anatomy_flash_dont_know")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_flash_stop"))
    return builder.as_markup()

def get_anatomy_flash_summary_keyboard(topic_key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_flash_start:{topic_key}")
    builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    return builder.as_markup()

async def render_anatomy_flash_question(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{DIVIDER}\n\n{card['front']}"
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_question_keyboard())

async def render_anatomy_flash_answer(message, user_id: int):
    session = ANATOMY_FLASH_SESSIONS[user_id]
    topic = get_anatomy_topic_data(session["topic_key"])
    total = len(session["cards"])
    card = topic["flashcards"][session["cards"][session["index"]]]
    text = (
        f"🎴 <b>Флэш-карточки — {session['index'] + 1}/{total}</b>\n{DIVIDER}\n\n"
        f"❓ {card['front']}\n\n💡 {card['back']}\n\n{DIVIDER}\nТы знал(а) ответ?"
    )
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_answer_keyboard())

async def render_anatomy_flash_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_FLASH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    answered = session["know"] + session["dont_know"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Карточки пройдены!</b>"
    text = (
        f"{title}\n{DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Знаю: <b>{session['know']}</b>\n❌ Не знаю: <b>{session['dont_know']}</b>"
    )
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=get_anatomy_flash_summary_keyboard(topic_key))

# ---- Сопоставление (матчинг как тест с вариантами) ----
def get_anatomy_all_pairs(topic_key: str):
    topic = get_anatomy_topic_data(topic_key)
    pairs = []
    for s in topic["matching_sets"]:
        pairs.extend(s["pairs"])
    return pairs

def start_anatomy_match_session(user_id: int, topic_key: str):
    all_pairs = get_anatomy_all_pairs(topic_key)
    size = min(ANATOMY_MATCH_SESSION_SIZE, len(all_pairs))
    ANATOMY_MATCH_SESSIONS[user_id] = {
        "topic_key": topic_key,
        "all_pairs": all_pairs,
        "queue": random.sample(all_pairs, size),
        "index": 0,
        "correct": 0,
        "wrong": 0,
        "current_correct_idx": None,
        "current_options": None,
    }

def get_anatomy_match_keyboard(options: list):
    builder = InlineKeyboardBuilder()
    for i in range(len(options)):
        builder.button(text=str(i + 1), callback_data=f"anatomy_match_answer:{i}")
    builder.adjust(len(options))
    builder.row(InlineKeyboardButton(text="🛑 Закончить", callback_data="anatomy_match_stop"))
    return builder.as_markup()

async def render_anatomy_match_question(message, user_id: int):
    session = ANATOMY_MATCH_SESSIONS[user_id]
    term, correct_def = session["queue"][session["index"]]
    distractor_pool = [d for t, d in session["all_pairs"] if d != correct_def]
    distractors = random.sample(distractor_pool, min(3, len(distractor_pool)))
    options = distractors + [correct_def]
    random.shuffle(options)
    session["current_correct_idx"] = options.index(correct_def)
    session["current_options"] = options
    lines = [
        f"🔗 <b>Сопоставление — {session['index'] + 1}/{len(session['queue'])}</b>\n{DIVIDER}\n",
        f"<b>{term}</b>\n",
        "Выбери правильное соответствие:",
        "",
    ]
    for i, opt in enumerate(options):
        lines.append(f"{i + 1}. {opt}")
    await safe_edit_text(message, "\n".join(lines), parse_mode="HTML", reply_markup=get_anatomy_match_keyboard(options))

async def render_anatomy_match_summary(message, user_id: int, aborted: bool = False):
    session = ANATOMY_MATCH_SESSIONS.pop(user_id, None)
    if not session:
        return
    topic_key = session["topic_key"]
    answered = session["correct"] + session["wrong"]
    title = "🛑 <b>Прервано</b>" if aborted else "🏁 <b>Сопоставление завершено!</b>"
    text = (
        f"{title}\n{DIVIDER}\n\n"
        f"Отвечено: <b>{answered}</b>\n✅ Верно: <b>{session['correct']}</b>\n❌ Неверно: <b>{session['wrong']}</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Пройти ещё раз", callback_data=f"anatomy_match_start:{topic_key}")
    builder.button(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}")
    builder.adjust(1)
    await safe_edit_text(message, text, parse_mode="HTML", reply_markup=builder.as_markup())

# ---- Мнемоники ----
def get_anatomy_mnemonics_keyboard(topic_key: str, idx: int):
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    builder = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx-1}"))
    if idx < len(mnemonics) - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"anatomy_mnemonics:{topic_key}:{idx+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 К разделу", callback_data=f"anatomy_topic:{topic_key}"))
    return builder.as_markup()

def get_anatomy_mnemonic_text(topic_key: str, idx: int) -> str:
    topic = get_anatomy_topic_data(topic_key)
    mnemonics = topic["mnemonics"]
    mn = mnemonics[idx]
    return f"🧠 <b>{mn['title']}</b>\n{DIVIDER}\n\n{mn['text']}\n\n{DIVIDER}\n{idx + 1}/{len(mnemonics)}"

# ---- Хендлеры ----
@dp.callback_query(F.data == "anatomy_menu")
async def cb_anatomy_menu(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🦴 <b>Анатомия</b>\n{DIVIDER}\n\nВыбери подраздел:",
        parse_mode="HTML",
        reply_markup=get_anatomy_menu_keyboard()
    )

@dp.callback_query(F.data == "anatomy_osteology")
async def cb_anatomy_osteology(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        f"🦴 <b>Остеология</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_osteology_keyboard()
    )

@dp.callback_query(F.data.startswith("anatomy_topic:"))
async def cb_anatomy_topic(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    text = (
        f"💀 <b>{topic['title']}</b>\n{DIVIDER}\n\n"
        f"📖 Материал: {len(topic['material'])} тем\n"
        f"🎴 Флэш-карточек: {len(topic['flashcards'])}\n"
        f"🔗 Пар для сопоставления: {sum(len(s['pairs']) for s in topic['matching_sets'])}\n"
        f"🧠 Мнемоник: {len(topic['mnemonics'])}\n\n"
        "Выбери формат подготовки:"
    )
    await safe_edit_text(callback.message, text, parse_mode="HTML", reply_markup=get_anatomy_topic_keyboard(topic_key))

@dp.callback_query(F.data.startswith("anatomy_material_list:"))
async def cb_anatomy_material_list(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    await safe_edit_text(
        callback.message,
        f"📋 <b>{topic['title']} — список тем</b>\n{DIVIDER}\n\nВыбери тему:",
        parse_mode="HTML",
        reply_markup=get_anatomy_material_list_keyboard(topic_key)
    )

@dp.callback_query(F.data.startswith("anatomy_material:"))
async def cb_anatomy_material(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, idx_s = callback.data.split(":")
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not (0 <= idx < len(topic["material"])):
        await callback.answer("Тема не найдена", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_anatomy_material_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_material_keyboard(topic_key, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_flash_start:"))
async def cb_anatomy_flash_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["flashcards"]:
        await callback.answer("Карточки ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_flash_session(callback.from_user.id, topic_key)
    await render_anatomy_flash_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "anatomy_flash_show_answer")
async def cb_anatomy_flash_show_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in ANATOMY_FLASH_SESSIONS:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    await render_anatomy_flash_answer(callback.message, user_id)

@dp.callback_query(F.data.in_({"anatomy_flash_know", "anatomy_flash_dont_know"}))
async def cb_anatomy_flash_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_FLASH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    await callback.answer()
    if callback.data == "anatomy_flash_know":
        session["know"] += 1
    else:
        session["dont_know"] += 1
    session["index"] += 1
    if session["index"] >= len(session["cards"]):
        await render_anatomy_flash_summary(callback.message, user_id)
    else:
        await render_anatomy_flash_question(callback.message, user_id)

@dp.callback_query(F.data == "anatomy_flash_stop")
async def cb_anatomy_flash_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_FLASH_SESSIONS:
        await render_anatomy_flash_summary(callback.message, callback.from_user.id, aborted=True)

@dp.callback_query(F.data.startswith("anatomy_match_start:"))
async def cb_anatomy_match_start(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    topic_key = callback.data.split(":")[1]
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not get_anatomy_all_pairs(topic_key):
        await callback.answer("Пары ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    start_anatomy_match_session(callback.from_user.id, topic_key)
    await render_anatomy_match_question(callback.message, callback.from_user.id)

@dp.callback_query(F.data.startswith("anatomy_match_answer:"))
async def cb_anatomy_match_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = ANATOMY_MATCH_SESSIONS.get(user_id)
    if not session:
        await callback.answer("Сессия истекла, начни заново", show_alert=True)
        return
    chosen = int(callback.data.split(":")[1])
    correct_idx = session["current_correct_idx"]
    if chosen == correct_idx:
        session["correct"] += 1
        await callback.answer("✅ Верно!")
    else:
        session["wrong"] += 1
        correct_text = session["current_options"][correct_idx]
        await callback.answer(f"❌ Неверно. Правильно: {correct_text}", show_alert=True)
    session["index"] += 1
    if session["index"] >= len(session["queue"]):
        await render_anatomy_match_summary(callback.message, user_id)
    else:
        await render_anatomy_match_question(callback.message, user_id)

@dp.callback_query(F.data == "anatomy_match_stop")
async def cb_anatomy_match_stop(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id in ANATOMY_MATCH_SESSIONS:
        await render_anatomy_match_summary(callback.message, callback.from_user.id, aborted=True)

@dp.callback_query(F.data.startswith("anatomy_mnemonics:"))
async def cb_anatomy_mnemonics(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    _, topic_key, idx_s = callback.data.split(":")
    idx = int(idx_s)
    topic = get_anatomy_topic_data(topic_key)
    if not topic or not topic["mnemonics"] or not (0 <= idx < len(topic["mnemonics"])):
        await callback.answer("Мнемоники ещё не добавлены", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        get_anatomy_mnemonic_text(topic_key, idx),
        parse_mode="HTML",
        reply_markup=get_anatomy_mnemonics_keyboard(topic_key, idx)
    )

@dp.callback_query(F.data.startswith("anatomy_picture:"))
async def cb_anatomy_picture(callback: CallbackQuery):
    if not anatomy_access_ok(callback.from_user.id):
        await callback.answer("Раздел пока в разработке", show_alert=True)
        return
    await callback.answer()
    topic_key = callback.data.split(":")[1]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"anatomy_topic:{topic_key}"))
    await safe_edit_text(
        callback.message,
        f"🖼 <b>Найди на картинке</b>\n{DIVIDER}\n\n"
        "🚧 Скоро будет добавлено — нужны изображения из атласов Неттера и Гайворонского.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

