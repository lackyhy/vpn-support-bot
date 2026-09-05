import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from x_ui.core import crypto_storage, bot_settings
from x_ui.core.api_client import format_bytes
from remnawave.core.api_client import RemnawaveClient
from remnawave.keyboards import inline as keyboards
from remnawave.states.states import RemnaUserStates

router = Router()

def format_iso_date(iso_str: str) -> str:
    if not iso_str:
        return "—"
    try:
        # standard ISO format: 2025-01-17T15:38:45.065Z
        cleaned = iso_str.split(".")[0].replace("Z", "")
        dt = datetime.datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_str

@router.callback_query(F.data == "remna_menu_users")
async def cb_users_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_users_page(callback, 0)

@router.callback_query(F.data.startswith("remna_users_page_"))
async def cb_users_page(callback: CallbackQuery):
    page = int(callback.data.replace("remna_users_page_", ""))
    await show_users_page(callback, page)

async def show_users_page(callback: CallbackQuery, page: int, query: str = None):
    lang = bot_settings.get_language()
    client = RemnawaveClient.from_storage()
    if not client:
        await callback.answer("Error initializing client" if lang == "en" else "Ошибка инициализации клиента", show_alert=True)
        return
        
    res = await client.get_users()
    await client.close()
    
    if not res.get("success", False):
        await callback.message.edit_text(
            f"❌ Error fetching users: {res.get('msg')}" if lang == "en" else f"❌ Ошибка получения пользователей: {res.get('msg')}",
            reply_markup=keyboards.cancel_kb(lang=lang)
        )
        await callback.answer()
        return
        
    response_data = res.get("response", {})
    users_list = response_data.get("users", []) if isinstance(response_data, dict) else []
    users = users_list
    if query:
        users = [u for u in users_list if query.lower() in u.get("username", "").lower()]
        
    total_users = len(users)
    limit = 8
    start_idx = page * limit
    end_idx = start_idx + limit
    
    page_users = users[start_idx:end_idx]
    has_prev = page > 0
    has_next = end_idx < total_users
    
    title = (
        f"👥 **Remnawave Users** (Total: {total_users})\nSelect a user to view details:"
        if lang == "en" else
        f"👥 **Пользователи Remnawave** (Всего: {total_users})\nВыберите пользователя для просмотра:"
    )
    if query:
        title = (
            f"🔍 **Search Results for '{query}'** (Found: {total_users}):"
            if lang == "en" else
            f"🔍 **Результаты поиска для '{query}'** (Найдено: {total_users}):"
        )
        
    await callback.message.edit_text(
        title,
        reply_markup=keyboards.users_list_kb(page_users, page, has_prev, has_next, lang=lang),
        parse_mode="Markdown"
    )
    await callback.answer()

def get_flag_emoji(country_code: str) -> str:
    if not country_code or len(country_code) != 2:
        return ""
    code = country_code.upper()
    try:
        return chr(127397 + ord(code[0])) + chr(127397 + ord(code[1]))
    except Exception:
        return ""

@router.callback_query(F.data.startswith("remna_user_view_"))
async def cb_user_view(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_view_", ""))
    
    client = RemnawaveClient.from_storage()
    import asyncio
    results = await asyncio.gather(
        client._request("GET", f"/api/users/{user_id}"),
        client.get_nodes(),
        client.get_squads(),
        return_exceptions=True
    )
    await client.close()
    
    user_res = results[0] if not isinstance(results[0], Exception) else {}
    nodes_res = results[1] if not isinstance(results[1], Exception) else {}
    squads_res = results[2] if not isinstance(results[2], Exception) else {}
    
    if not user_res.get("success", False):
        await callback.answer(f"Error: {user_res.get('msg')}", show_alert=True)
        return
        
    user = user_res.get("response", {})
    username = user.get("username", "Unknown")
    status = user.get("status", "ACTIVE")
    
    status_icon = "🟢 ACTIVE" if status == "ACTIVE" else ("🔴 DISABLED" if status == "DISABLED" else f"⚠️ {status}")
    if lang == "ru":
        status_icon = "🟢 АКТИВЕН" if status == "ACTIVE" else ("🔴 ОТКЛЮЧЕН" if status == "DISABLED" else f"⚠️ {status}")
        
    expire_at = format_iso_date(user.get("expireAt"))
    traffic_limit = user.get("trafficLimitBytes", 0)
    traffic_limit_str = format_bytes(traffic_limit) if traffic_limit > 0 else ("Unlimited" if lang == "en" else "Безлимит")
    
    traffic_info = user.get("userTraffic", {})
    used_traffic = traffic_info.get("usedTrafficBytes", 0)
    used_str = format_bytes(used_traffic)
    lifetime_traffic = traffic_info.get("lifetimeUsedTrafficBytes", 0)
    lifetime_str = format_bytes(lifetime_traffic)
    
    hwid_limit = user.get("hwidDeviceLimit", 0)
    hwid_limit_str = f"{hwid_limit}" if hwid_limit and hwid_limit > 0 else ("Unlimited" if lang == "en" else "Безлимит")
    
    sub_url = user.get("subscriptionUrl", "—")
    
    # Node lookup for last/active connected node
    node_lookup = {}
    if isinstance(nodes_res, dict) and nodes_res.get("success"):
        for n in nodes_res.get("response", []):
            uuid = n.get("uuid")
            name = n.get("name", "Node")
            cc = n.get("countryCode")
            flag = get_flag_emoji(cc) if cc else ""
            node_lookup[uuid] = f"{flag} {name}".strip()
            
    last_node_uuid = traffic_info.get("lastConnectedNodeUuid")
    last_node_name = node_lookup.get(last_node_uuid) if last_node_uuid else None
    
    # Check online status (real-time connected check)
    is_online = False
    if user.get("isOnline") is True or traffic_info.get("isOnline") is True:
        is_online = True
    else:
        online_st = str(user.get("onlineStatus") or traffic_info.get("onlineStatus") or "").upper()
        if online_st in ["ONLINE", "CONNECTED"]:
            is_online = True
        elif online_st in ["OFFLINE", "DISCONNECTED"]:
            is_online = False
        else:
            raw_online_at = traffic_info.get("onlineAt") or user.get("onlineAt")
            if raw_online_at:
                try:
                    cleaned = str(raw_online_at).split(".")[0].replace("Z", "")
                    dt = datetime.datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S")
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    diff_sec = (now_utc - dt).total_seconds()
                    if 0 <= diff_sec <= 180:
                        is_online = True
                except Exception:
                    pass

    if is_online:
        if last_node_name:
            online_status_str = f"🟢 Connected ({last_node_name})" if lang == "en" else f"🟢 Подключен ({last_node_name})"
        else:
            online_status_str = "🟢 Connected" if lang == "en" else "🟢 Подключен"
    else:
        online_status_str = "🔴 Disconnected" if lang == "en" else "🔴 Отключен"

    # Squad lookup & extraction
    squad_lookup = {}
    if isinstance(squads_res, dict) and squads_res.get("success"):
        resp_obj = squads_res.get("response", [])
        if isinstance(resp_obj, list):
            squads_list = resp_obj
        elif isinstance(resp_obj, dict):
            squads_list = resp_obj.get("internalSquads") or resp_obj.get("squads") or resp_obj.get("items") or []
        else:
            squads_list = []

        for sq in squads_list:
            if isinstance(sq, dict):
                s_uuid = sq.get("uuid") or sq.get("id")
                s_name = sq.get("name") or sq.get("title")
                if s_uuid and s_name:
                    squad_lookup[str(s_uuid)] = str(s_name)

    def resolve_squad(u: dict, lookup: dict) -> str:
        candidates = [
            u.get("internalSquads"),
            u.get("internalSquad"),
            u.get("activeInternalSquads"),
            u.get("userInternalSquads"),
            u.get("squads"),
            u.get("squad"),
            u.get("activeSquad")
        ]
        
        sq_val = None
        for cand in candidates:
            if cand is not None and cand != [] and cand != "":
                sq_val = cand
                break

        if sq_val:
            if isinstance(sq_val, str):
                return lookup.get(sq_val, sq_val)
            elif isinstance(sq_val, dict):
                name = sq_val.get("name") or sq_val.get("title")
                if name:
                    return name
                uuid = sq_val.get("uuid") or sq_val.get("id")
                if uuid and str(uuid) in lookup:
                    return lookup[str(uuid)]
            elif isinstance(sq_val, list):
                res_names = []
                for item in sq_val:
                    if isinstance(item, str):
                        res_names.append(lookup.get(item, item))
                    elif isinstance(item, dict):
                        n = item.get("name") or item.get("title") or lookup.get(str(item.get("uuid")), "")
                        if n:
                            res_names.append(n)
                if res_names:
                    return ", ".join(res_names)

        if u.get("internalSquadName"):
            return str(u.get("internalSquadName"))
        if u.get("squadName"):
            return str(u.get("squadName"))

        sq_uuid = u.get("internalSquadUuid") or u.get("squadUuid") or u.get("squadId")
        if sq_uuid and str(sq_uuid) in lookup:
            return lookup[str(sq_uuid)]

        return "—"

    squad_str = resolve_squad(user, squad_lookup)

    text = (
        f"👤 **User Detail: {username}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID**: `{user_id}`\n"
        f"⚡ **Status**: {status_icon}\n"
        f"🌐 **Online**: {online_status_str}\n"
        f"🛡 **Squad**: {squad_str}\n"
        f"⏳ **Expires**: {expire_at}\n"
        f"🚦 **Traffic used**: {used_str} / {traffic_limit_str}\n"
        f"📈 **Lifetime Traffic**: {lifetime_str}\n"
        f"📱 **HWID Limit**: {hwid_limit_str}\n\n"
        f"🔑 **Subscription Link**:\n`{sub_url}`"
        if lang == "en" else
        f"👤 **Детали пользователя: {username}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID**: `{user_id}`\n"
        f"⚡ **Статус**: {status_icon}\n"
        f"🌐 **Онлайн**: {online_status_str}\n"
        f"🛡 **Сквад**: {squad_str}\n"
        f"⏳ **Истекает**: {expire_at}\n"
        f"🚦 **Использовано**: {used_str} / {traffic_limit_str}\n"
        f"📈 **Трафик за всё время**: {lifetime_str}\n"
        f"📱 **Лимит устройств (HWID)**: {hwid_limit_str}\n\n"
        f"🔑 **Ссылка подписки**:\n`{sub_url}`"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.user_detail_kb(user_id, status, lang=lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("remna_user_toggle_"))
async def cb_user_toggle(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_toggle_", ""))
    
    client = RemnawaveClient.from_storage()
    res = await client._request("GET", f"/api/users/{user_id}")
    if not res.get("success"):
        await client.close()
        await callback.answer(f"Error: {res.get('msg')}", show_alert=True)
        return
        
    user = res.get("response", {})
    status = user.get("status", "ACTIVE")
    
    if status == "ACTIVE":
        res_action = await client.disable_user(user_id)
    else:
        res_action = await client.enable_user(user_id)
        
    await client.close()
    
    if res_action.get("success"):
        await callback.answer("Status updated!" if lang == "en" else "Статус обновлен!", show_alert=True)
        # Refresh details
        await cb_user_view(callback)
    else:
        await callback.answer(f"Failed: {res_action.get('msg')}", show_alert=True)

@router.callback_query(F.data.startswith("remna_user_reset_"))
async def cb_user_reset(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_reset_", ""))
    
    client = RemnawaveClient.from_storage()
    res = await client.reset_user_traffic(user_id)
    await client.close()
    
    if res.get("success"):
        await callback.answer("Traffic limit reset!" if lang == "en" else "Трафик сброшен!", show_alert=True)
        await cb_user_view(callback)
    else:
        await callback.answer(f"Failed: {res.get('msg')}", show_alert=True)

@router.callback_query(F.data.startswith("remna_user_delete_"))
async def cb_user_delete(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_delete_", ""))
    
    client = RemnawaveClient.from_storage()
    res = await client.delete_user(user_id)
    await client.close()
    
    if res.get("success"):
        await callback.answer("User deleted!" if lang == "en" else "Пользователь удален!", show_alert=True)
        await show_users_page(callback, 0)
    else:
        await callback.answer(f"Failed: {res.get('msg')}", show_alert=True)

# EXTEND USER EXPIRATION
@router.callback_query(F.data.startswith("remna_user_extend_"))
async def cb_user_extend_start(callback: CallbackQuery, state: FSMContext):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_extend_", ""))
    await state.update_data(user_id=user_id)
    await state.set_state(RemnaUserStates.waiting_for_extend_days)
    
    text = (
        "⏳ **Extend Expiration**\n\nEnter the number of days to extend this user's access:"
        if lang == "en" else
        "⏳ **Продление доступа**\n\nВведите число дней, на которое нужно продлить доступ пользователя:"
    )
    await callback.message.edit_text(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")
    await callback.answer()

@router.message(RemnaUserStates.waiting_for_extend_days)
async def process_user_extend(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    data = await state.get_data()
    user_id = data.get("user_id")
    
    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Please enter a positive integer!" if lang == "en" else "❌ Пожалуйста, введите целое положительное число!")
        return

    client = RemnawaveClient.from_storage()
    res = await client.extend_user(user_id, days)
    await client.close()
    
    if res.get("success"):
        await message.answer("✅ Expiration date extended!" if lang == "en" else "✅ Срок действия успешно продлен!")
    else:
        await message.answer(f"❌ Failed: {res.get('msg')}")
        
    await state.clear()
    # Mocking call to refresh detail view
    # We will trigger show_remna_dashboard as fallback or let them open the menu
    # To keep FSM cleanup robust we return to start dashboard
    from remnawave.handlers.start import show_remna_dashboard
    await show_remna_dashboard(message, state)

# EDIT TRAFFIC LIMIT
@router.callback_query(F.data.startswith("remna_user_limit_"))
async def cb_user_limit_start(callback: CallbackQuery, state: FSMContext):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_limit_", ""))
    await state.update_data(user_id=user_id)
    await state.set_state(RemnaUserStates.waiting_for_edit_gb)
    
    text = (
        "✏️ **Edit Traffic Limit**\n\nEnter new traffic limit in **GB** (enter `0` for unlimited):"
        if lang == "en" else
        "✏️ **Изменение лимита трафика**\n\nВведите новый лимит трафика в **ГБ** (введите `0` для безлимита):"
    )
    await callback.message.edit_text(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")
    await callback.answer()

@router.message(RemnaUserStates.waiting_for_edit_gb)
async def process_user_limit(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    data = await state.get_data()
    user_id = data.get("user_id")
    
    try:
        gb = float(message.text.strip())
        if gb < 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Invalid input. Please enter a valid number!" if lang == "en" else "❌ Некорректный ввод. Введите число!")
        return

    bytes_limit = int(gb * 1024 * 1024 * 1024)
    client = RemnawaveClient.from_storage()
    res = await client.update_user(user_id, {"trafficLimitBytes": bytes_limit})
    await client.close()
    
    if res.get("success"):
        await message.answer("✅ Traffic limit updated!" if lang == "en" else "✅ Лимит трафика обновлен!")
    else:
        await message.answer(f"❌ Failed: {res.get('msg')}")
        
    await state.clear()
    from remnawave.handlers.start import show_remna_dashboard
    await show_remna_dashboard(message, state)

# VIEW & MANAGE HWID DEVICES
@router.callback_query(F.data.startswith("remna_user_devices_"))
async def cb_user_devices(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_devices_", ""))

    client = RemnawaveClient.from_storage()
    user_res = await client._request("GET", f"/api/users/{user_id}")
    
    if not user_res.get("success", False):
        await client.close()
        await callback.answer(f"Error: {user_res.get('msg')}", show_alert=True)
        return

    user = user_res.get("response", {})
    username = user.get("username", "Unknown")
    user_uuid = user.get("uuid")

    devices_res = await client.get_user_hwid_devices(user_id, username=username, user_uuid=user_uuid)
    await client.close()

    hwid_limit = user.get("hwidDeviceLimit", 0)
    hwid_limit_str = f"{hwid_limit}" if hwid_limit and hwid_limit > 0 else ("Unlimited" if lang == "en" else "Безлимит")

    devices = []
    if isinstance(devices_res, dict) and devices_res.get("success"):
        resp_d = devices_res.get("response", [])
        if isinstance(resp_d, list):
            devices = resp_d
        elif isinstance(resp_d, dict):
            devices = (
                resp_d.get("devices") or 
                resp_d.get("hwidDevices") or 
                resp_d.get("userHwidDevices") or
                resp_d.get("internalHwidDevices") or
                resp_d.get("items") or 
                []
            )

    if not devices:
        devices = (
            user.get("userHwidDevices") or
            user.get("hwidDevices") or 
            user.get("internalHwidDevices") or
            user.get("devices") or 
            user.get("userDevices") or 
            user.get("hwids") or
            user.get("userTraffic", {}).get("hwidDevices") or 
            user.get("userTraffic", {}).get("devices") or
            []
        )

    dev_count = len(devices)

    lines = []
    if lang == "en":
        lines.append(f"📱 **HWID Devices for user: {username}**")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"🆔 **ID**: `{user_id}`")
        lines.append(f"📏 **HWID Limit**: `{hwid_limit_str}`")
        lines.append(f"📊 **Registered Devices**: `{dev_count}`\n")
    else:
        lines.append(f"📱 **Устройства HWID пользователя: {username}**")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"🆔 **ID**: `{user_id}`")
        lines.append(f"📏 **Лимит устройств (HWID)**: `{hwid_limit_str}`")
        lines.append(f"📊 **Привязано устройств**: `{dev_count}`\n")

    if devices:
        for idx, dev in enumerate(devices):
            icon = "📱"
            plat_str = ""
            model_str = ""

            if isinstance(dev, dict):
                platform = dev.get("platform") or dev.get("os") or ""
                model = dev.get("model") or dev.get("name") or dev.get("title") or dev.get("device") or ""

                if platform:
                    plat_l = str(platform).lower()
                    if "win" in plat_l:
                        icon = "💻"
                    elif "ios" in plat_l or "iphone" in plat_l or "ipad" in plat_l:
                        icon = "📱"
                    elif "mac" in plat_l or "apple" in plat_l:
                        icon = "💻"
                    elif "android" in plat_l:
                        icon = "🤖"
                    elif "linux" in plat_l:
                        icon = "🐧"
                    plat_str = str(platform)
                if model:
                    model_str = f" ({model})"

            info_part = f"{plat_str}{model_str}".strip()
            if not info_part and isinstance(dev, str):
                info_part = f"`{dev[:12]}...`"
            elif not info_part:
                info_part = "Device" if lang == "en" else "Устройство"

            lines.append(f"{icon} **#{idx+1}**: {info_part}")
    else:
        lines.append("ℹ️ No registered devices yet." if lang == "en" else "ℹ️ Привязанных устройств пока нет.")

    text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.user_devices_kb(user_id, devices, lang=lang),
        parse_mode="Markdown"
    )
    await callback.answer()

# SINGLE DEVICE DETAIL VIEW
@router.callback_query(F.data.startswith("remna_dev_view_"))
async def cb_single_device_view(callback: CallbackQuery):
    lang = bot_settings.get_language()
    parts = callback.data.replace("remna_dev_view_", "").split("_")
    user_id = int(parts[0])
    idx = int(parts[1])

    client = RemnawaveClient.from_storage()
    user_res = await client._request("GET", f"/api/users/{user_id}")
    if not user_res.get("success", False):
        await client.close()
        await callback.answer(f"Error: {user_res.get('msg')}", show_alert=True)
        return

    user = user_res.get("response", {})
    username = user.get("username", "Unknown")
    user_uuid = user.get("uuid")

    devices_res = await client.get_user_hwid_devices(user_id, username=username, user_uuid=user_uuid)
    await client.close()

    devices = []
    if isinstance(devices_res, dict) and devices_res.get("success"):
        resp_d = devices_res.get("response", [])
        if isinstance(resp_d, list):
            devices = resp_d
        elif isinstance(resp_d, dict):
            devices = (
                resp_d.get("devices") or 
                resp_d.get("hwidDevices") or 
                resp_d.get("userHwidDevices") or
                resp_d.get("internalHwidDevices") or
                resp_d.get("items") or 
                []
            )

    if not devices:
        devices = (
            user.get("userHwidDevices") or
            user.get("hwidDevices") or 
            user.get("internalHwidDevices") or
            user.get("devices") or 
            user.get("userDevices") or 
            user.get("hwids") or
            user.get("userTraffic", {}).get("hwidDevices") or 
            user.get("userTraffic", {}).get("devices") or
            []
        )

    if idx < 0 or idx >= len(devices):
        await callback.answer("Device not found" if lang == "en" else "Устройство не найдено", show_alert=True)
        return

    dev = devices[idx]
    dev_identifier = str(idx)

    lines = []
    if isinstance(dev, dict):
        dev_id_raw = dev.get("id") or dev.get("uuid") or dev.get("hwid")
        if dev_id_raw:
            dev_identifier = str(dev_id_raw)

        d_platform = dev.get("platform") or dev.get("os")
        d_model = dev.get("model") or dev.get("name") or dev.get("title") or dev.get("device")
        d_hwid = dev.get("hwid") or dev.get("id") or dev.get("uuid") or dev.get("fingerprint")
        d_ip = dev.get("ipAddress") or dev.get("ip_address") or dev.get("ip")
        d_ua = dev.get("userAgent") or dev.get("user_agent")
        d_updated = dev.get("updatedAt") or dev.get("lastOnlineAt") or dev.get("lastSeenAt") or dev.get("onlineAt")
        d_created = dev.get("createdAt")

        icon = "📱"
        if d_platform:
            plat_l = str(d_platform).lower()
            if "win" in plat_l:
                icon = "💻"
            elif "ios" in plat_l or "iphone" in plat_l or "ipad" in plat_l:
                icon = "📱"
            elif "mac" in plat_l or "apple" in plat_l:
                icon = "💻"
            elif "android" in plat_l:
                icon = "🤖"

        hwid_disp = f"`{d_hwid}`" if d_hwid else "—"
        updated_disp = format_iso_date(d_updated) if d_updated else "—"
        created_disp = format_iso_date(d_created) if d_created else "—"

        plat_title = f"{d_platform}" if d_platform else "Device"
        lines.append(f"{icon} **{plat_title} #{idx+1}**" if lang == "en" else f"{icon} **Устройство #{idx+1} ({plat_title})**")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"👤 **User**: `{username}`" if lang == "en" else f"👤 **Пользователь**: `{username}`")
        if d_model:
            lines.append(f"📱 **Model**: {d_model}" if lang == "en" else f"📱 **Модель**: {d_model}")
        lines.append(f"🔑 **HWID**: {hwid_disp}")
        if d_ip:
            lines.append(f"🌐 **IP Address**: `{d_ip}`" if lang == "en" else f"🌐 **IP-адрес**: `{d_ip}`")
        if d_ua:
            lines.append(f"📡 **User Agent**: `{d_ua}`")
        if created_disp != "—":
            lines.append(f"⏳ **Created**: {created_disp}" if lang == "en" else f"⏳ **Создан**: {created_disp}")
        if updated_disp != "—":
            lines.append(f"🔄 **Updated**: {updated_disp}" if lang == "en" else f"🔄 **Обновлен**: {updated_disp}")
    else:
        lines.append(f"📱 **Device #{idx+1}**: `{str(dev)}`")

    text = "\n".join(lines)
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.single_device_kb(user_id, dev_identifier, lang=lang),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("remna_dev_clear_"))
async def cb_user_dev_clear(callback: CallbackQuery):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_dev_clear_", ""))

    client = RemnawaveClient.from_storage()
    res = await client.clear_user_hwid_devices(user_id)
    await client.close()

    if res.get("success"):
        await callback.answer("All devices cleared!" if lang == "en" else "Все привязки устройств сброшены!", show_alert=True)
        await cb_user_devices(callback)
    else:
        await callback.answer(f"Failed: {res.get('msg')}", show_alert=True)

@router.callback_query(F.data.startswith("remna_dev_del_"))
async def cb_user_dev_del(callback: CallbackQuery):
    lang = bot_settings.get_language()
    parts = callback.data.replace("remna_dev_del_", "").split("_")
    user_id = int(parts[0])
    dev_id = "_".join(parts[1:])

    client = RemnawaveClient.from_storage()
    res = await client.delete_hwid_device(user_id, dev_id)
    await client.close()

    if res.get("success"):
        await callback.answer("Device deleted!" if lang == "en" else "Устройство удалено!", show_alert=True)
        await cb_user_devices(callback)
    else:
        await callback.answer(f"Failed: {res.get('msg')}", show_alert=True)

# EDIT HWID LIMIT
@router.callback_query(F.data.startswith("remna_user_hwid_"))
async def cb_user_hwid_start(callback: CallbackQuery, state: FSMContext):
    lang = bot_settings.get_language()
    user_id = int(callback.data.replace("remna_user_hwid_", ""))
    await state.update_data(user_id=user_id)
    await state.set_state(RemnaUserStates.waiting_for_edit_hwid)
    
    text = (
        "📱 **Edit HWID Limit**\n\nEnter maximum number of devices allowed (enter `0` for unlimited):"
        if lang == "en" else
        "📱 **Изменение лимита устройств**\n\nВведите максимальное число устройств (введите `0` для безлимита):"
    )
    await callback.message.edit_text(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")
    await callback.answer()

@router.message(RemnaUserStates.waiting_for_edit_hwid)
async def process_user_hwid(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    data = await state.get_data()
    user_id = data.get("user_id")
    
    try:
        hwid = int(message.text.strip())
        if hwid < 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Please enter a non-negative integer!" if lang == "en" else "❌ Введите целое неотрицательное число!")
        return

    client = RemnawaveClient.from_storage()
    res = await client.update_user(user_id, {"hwidDeviceLimit": hwid})
    await client.close()
    
    if res.get("success"):
        await message.answer("✅ HWID limit updated!" if lang == "en" else "✅ Лимит устройств обновлен!")
    else:
        await message.answer(f"❌ Failed: {res.get('msg')}")
        
    await state.clear()
    from remnawave.handlers.start import show_remna_dashboard
    await show_remna_dashboard(message, state)

# SEARCH USER
@router.callback_query(F.data == "remna_user_search")
async def cb_user_search_start(callback: CallbackQuery, state: FSMContext):
    lang = bot_settings.get_language()
    await state.set_state(RemnaUserStates.waiting_for_search_query)
    
    text = (
        "🔍 **Search User**\n\nEnter part of the username to search:"
        if lang == "en" else
        "🔍 **Поиск пользователя**\n\nВведите часть имени пользователя для поиска:"
    )
    await callback.message.edit_text(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")
    await callback.answer()

@router.message(RemnaUserStates.waiting_for_search_query)
async def process_user_search(message: Message, state: FSMContext):
    query = message.text.strip()
    # We display search results directly on the users list with pagination
    # To do this, we mock a callback view
    # Custom message helper
    lang = bot_settings.get_language()
    client = RemnawaveClient.from_storage()
    if not client:
        await message.answer("Error" if lang == "en" else "Ошибка")
        return
    res = await client.get_users()
    await client.close()
    
    if not res.get("success"):
        await message.answer(f"Error: {res.get('msg')}")
        await state.clear()
        return
        
    response_data = res.get("response", {})
    users_list = response_data.get("users", []) if isinstance(response_data, dict) else []
    users = [u for u in users_list if query.lower() in u.get("username", "").lower()]
    total_users = len(users)
    page_users = users[:8]
    has_next = total_users > 8
    
    await state.clear()
    
    title = (
        f"🔍 **Search Results for '{query}'** (Found: {total_users}):"
        if lang == "en" else
        f"🔍 **Результаты поиска для '{query}'** (Найдено: {total_users}):"
    )
    await message.answer(
        title,
        reply_markup=keyboards.users_list_kb(page_users, 0, False, has_next, lang=lang),
        parse_mode="Markdown"
    )

# CREATE USER FLOW
@router.callback_query(F.data == "remna_user_create")
async def cb_user_create_start(callback: CallbackQuery, state: FSMContext):
    lang = bot_settings.get_language()
    await state.set_state(RemnaUserStates.waiting_for_username)
    text = (
        "👥 **Create Remnawave User** (Step 1 of 4)\n\nEnter username:"
        if lang == "en" else
        "👥 **Создание пользователя Remnawave** (Шаг 1 из 4)\n\nВведите имя пользователя (username):"
    )
    await callback.message.edit_text(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")
    await callback.answer()

@router.message(RemnaUserStates.waiting_for_username)
async def process_create_username(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    username = message.text.strip()
    if len(username) < 3 or len(username) > 36:
        await message.answer("❌ Username must be 3-36 characters!" if lang == "en" else "❌ Имя пользователя должно быть от 3 до 36 символов!")
        return
        
    await state.update_data(username=username)
    await state.set_state(RemnaUserStates.waiting_for_expiry)
    
    text = (
        f"👤 **Creating User `{username}`** (Step 2 of 4)\n\nEnter duration in **days**:"
        if lang == "en" else
        f"👤 **Создание пользователя `{username}`** (Шаг 2 из 4)\n\nВведите срок действия в **днях**:"
    )
    await message.answer(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")

@router.message(RemnaUserStates.waiting_for_expiry)
async def process_create_expiry(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Please enter a positive integer!" if lang == "en" else "❌ Пожалуйста, введите целое положительное число!")
        return
        
    await state.update_data(expiry_days=days)
    await state.set_state(RemnaUserStates.waiting_for_limit_gb)
    
    text = (
        f"👤 **Creating User** (Step 3 of 4)\n\nEnter traffic limit in **GB** (enter `0` for unlimited):"
        if lang == "en" else
        f"👤 **Создание пользователя** (Шаг 3 из 4)\n\nВведите лимит трафика в **ГБ** (введите `0` для безлимита):"
    )
    await message.answer(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")

@router.message(RemnaUserStates.waiting_for_limit_gb)
async def process_create_limit(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    try:
        gb = float(message.text.strip())
        if gb < 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Please enter a valid number!" if lang == "en" else "❌ Пожалуйста, введите число!")
        return
        
    await state.update_data(limit_gb=gb)
    await state.set_state(RemnaUserStates.waiting_for_hwid)
    
    text = (
        f"👤 **Creating User** (Step 4 of 4)\n\nEnter HWID limit / device limit (enter `0` for unlimited):"
        if lang == "en" else
        f"👤 **Создание пользователя** (Шаг 4 из 4)\n\nВведите лимит устройств (введите `0` для безлимита):"
    )
    await message.answer(text, reply_markup=keyboards.cancel_kb(lang=lang), parse_mode="Markdown")

@router.message(RemnaUserStates.waiting_for_hwid)
async def process_create_hwid(message: Message, state: FSMContext):
    lang = bot_settings.get_language()
    try:
        hwid = int(message.text.strip())
        if hwid < 0:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Please enter a non-negative integer!" if lang == "en" else "❌ Введите целое неотрицательное число!")
        return
        
    data = await state.get_data()
    username = data.get("username")
    expiry_days = data.get("expiry_days")
    limit_gb = data.get("limit_gb")
    
    bytes_limit = int(limit_gb * 1024 * 1024 * 1024)
    
    # Calculate ISO expiration string
    exp_date = datetime.datetime.utcnow() + datetime.timedelta(days=expiry_days)
    expire_str = exp_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    status_msg = await message.answer("🔄 **Creating user in Remnawave...**" if lang == "en" else "🔄 **Создание пользователя в Remnawave...**")
    
    client = RemnawaveClient.from_storage()
    res = await client.create_user(username, expire_str, bytes_limit, hwid)
    await client.close()
    
    if res.get("success"):
        user_info = res.get("response", {})
        sub_url = user_info.get("subscriptionUrl", "")
        
        success_text = (
            f"✅ **User `{username}` successfully created!**\n\n"
            f"⏳ **Expires**: {expiry_days} days\n"
            f"🚦 **Traffic limit**: {limit_gb} GB\n"
            f"📱 **Device limit**: {hwid if hwid > 0 else 'Unlimited'}\n\n"
            f"🔑 **Subscription Link**:\n`{sub_url}`"
            if lang == "en" else
            f"✅ **Пользователь `{username}` успешно создан!**\n\n"
            f"⏳ **Срок действия**: {expiry_days} дней\n"
            f"🚦 **Лимит трафика**: {limit_gb} ГБ\n"
            f"📱 **Лимит устройств**: {hwid if hwid > 0 else 'Безлимит'}\n\n"
            f"🔑 **Ссылка подписки**:\n`{sub_url}`"
        )
        await status_msg.edit_text(success_text, parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ **Failed to create user!**\n\nReason: `{res.get('msg')}`")
        
    await state.clear()
    
    from remnawave.handlers.start import show_remna_dashboard
    # Trigger menu return
    await show_remna_dashboard(message, state)
