# -*- coding: utf-8 -*-
import json
import os
import time
import traceback
import sys
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

# ================== КОНФИГУРАЦИЯ ==================
VK_TOKEN = "vk1.a.suDZ0i6S6HzjJauZqjy6bYIUpAgdd4i_WFkl3DNg21iqlJw2JLXfL408SNtfjEVxE22ldUd_zpSUozgklmMPf4vV5h9EPfZSTNHX5D8UixMKPhNoEVRgIFa5__EMlHefWxNEV5IZBEqmho-mm3cjbEBjLeUCSzfPKfg3RgraxpaRMwJGxuAE2dxbauRhET1Rb1nbH7YrWV8iDl8RE3qPZA"
GROUP_ID = 235847227
ADMIN_IDS = [1081585968, 472671974]
YANDEX_API_KEY = "c71c748b-9fc9-4235-9e20-048747ef156d"

DRIVERS_FILE = "drivers.json"
OPERATORS_FILE = "operators.json"
ORDERS_FILE = "orders.json"
ERROR_LOG_FILE = "error.log"
ORDERS_COUNTER_FILE = "orders_counter.json"
SHIFTS_FILE = "shifts.json"
PRICES_FILE = "prices.json"
CALLBACKS_FILE = "callbacks.json"
SETTINGS_FILE = "settings.json"

DEFAULT_PHONE = "+7 (999) 123-45-67"
DEFAULT_WELCOME = "🚕 Добро пожаловать в чат таксопарка!\n\nДля заказа такси напишите в личные сообщения или позвоните: {phone}"
DEFAULT_GOODBYE = "👋 Пользователь покинул чат. Всего доброго!"
DEFAULT_ORDER_MSG = "🚕 Закажите такси прямо сейчас!\n\n📞 Звоните: {phone}\n💬 Или напишите нам в личные сообщения."
DEFAULT_LS_ERROR_MSG = "⚠️ @id{user_id}, не могу написать вам в личные сообщения.\n\nПожалуйста, напишите боту первым: vk.me/club{group_id}\nИли позвоните: {phone}"

def log_error(text):
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] {text}\n{'-'*50}\n")
    except:
        pass

def load_json(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        log_error(str(e))
        return False

def init_files():
    if not os.path.exists(DRIVERS_FILE):
        save_json(DRIVERS_FILE, {})
    if not os.path.exists(OPERATORS_FILE):
        save_json(OPERATORS_FILE, ADMIN_IDS.copy())
    if not os.path.exists(ORDERS_FILE):
        save_json(ORDERS_FILE, [])
    if not os.path.exists(ORDERS_COUNTER_FILE):
        save_json(ORDERS_COUNTER_FILE, {"counter": 0})
    if not os.path.exists(SHIFTS_FILE):
        save_json(SHIFTS_FILE, {})
    if not os.path.exists(PRICES_FILE):
        save_json(PRICES_FILE, {"price_per_km": 25.0, "night_coeff": 1.5})
    if not os.path.exists(CALLBACKS_FILE):
        save_json(CALLBACKS_FILE, [])
    if not os.path.exists(SETTINGS_FILE):
        save_json(SETTINGS_FILE, {
            "welcome_msg": DEFAULT_WELCOME, "goodbye_msg": DEFAULT_GOODBYE,
            "order_msg": DEFAULT_ORDER_MSG, "ls_error_msg": DEFAULT_LS_ERROR_MSG, "phone": DEFAULT_PHONE
        })

def get_next_order_id():
    counter = load_json(ORDERS_COUNTER_FILE)
    counter["counter"] += 1
    save_json(ORDERS_COUNTER_FILE, counter)
    return counter["counter"]

def suggest_address(text):
    try:
        url = "https://suggest-maps.yandex.ru/v1/suggest"
        params = {"apikey": YANDEX_API_KEY, "text": text, "lang": "ru", "results": 5}
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        suggestions = []
        results = data.get("results", [])
        for item in results:
            title = item.get("title", {})
            if isinstance(title, dict):
                text_addr = title.get("text", "")
                if text_addr:
                    suggestions.append(text_addr)
                    continue
            if isinstance(item, str):
                suggestions.append(item)
                continue
            subtitle = item.get("subtitle", {})
            if isinstance(subtitle, dict):
                text_addr = subtitle.get("text", "")
                if text_addr:
                    suggestions.append(text_addr)
        return suggestions
    except Exception as e:
        log_error(f"Yandex suggest error: {e}")
        return []

def get_coordinates(address):
    try:
        url = "https://geocode-maps.yandex.ru/1.x/"
        params = {"apikey": YANDEX_API_KEY, "geocode": address, "format": "json", "results": 1}
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        members = data.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])
        if members:
            pos = members[0]['GeoObject']['Point']['pos']
            lon, lat = pos.split()
            return float(lat), float(lon)
    except Exception as e:
        log_error(f"Yandex geocode error: {e}")
    return None, None

def get_route_multi(points):
    try:
        if len(points) < 2:
            return 0, 0
        waypoints = "|".join(f"{lon},{lat}" for lat, lon in points)
        url = "https://api.routing.yandex.net/v2/route"
        params = {"apikey": YANDEX_API_KEY, "waypoints": waypoints, "mode": "driving"}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        route = data.get('route', {})
        if route and route.get('legs'):
            d = sum(leg.get('distance', 0) for leg in route['legs'])
            t = sum(leg.get('duration', 0) for leg in route['legs'])
            return round(d / 1000, 1), round(t / 60)
    except Exception as e:
        log_error(f"Yandex route error: {e}")
    return 0, 0

def is_night_time():
    h = datetime.now().hour
    return h >= 22 or h < 6

class TaxiBot:
    def __init__(self):
        init_files()
        self.vk_session = vk_api.VkApi(token=VK_TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, GROUP_ID)
        self.drivers = load_json(DRIVERS_FILE) or {}
        self.operators = load_json(OPERATORS_FILE) or ADMIN_IDS.copy()
        self.shifts = load_json(SHIFTS_FILE) or {}
        self.prices = load_json(PRICES_FILE) or {"price_per_km": 25.0, "night_coeff": 1.5}
        self.callbacks = load_json(CALLBACKS_FILE) or []
        self.settings = load_json(SETTINGS_FILE) or {"welcome_msg": DEFAULT_WELCOME, "goodbye_msg": DEFAULT_GOODBYE, "order_msg": DEFAULT_ORDER_MSG, "ls_error_msg": DEFAULT_LS_ERROR_MSG, "phone": DEFAULT_PHONE}
        self.phone = self.settings.get("phone", DEFAULT_PHONE)
        self.admin_roles = {aid: set() for aid in ADMIN_IDS}
        self.states = {}
        self.temp = {}
        self.pending_orders = {}
        self.active_orders = {}
        self.driver_current_order = {}
        print("✅ Бот инициализирован")

    def is_admin(self, uid): return uid in ADMIN_IDS
    def get_msg(self, key, **kw):
        m = self.settings.get(key, "").replace("{phone}", self.phone).replace("{group_id}", str(GROUP_ID))
        for k, v in kw.items(): m = m.replace(f"{{{k}}}", str(v))
        return m
    def calculate_price(self, km):
        p = km * self.prices.get("price_per_km", 25)
        if is_night_time(): p *= self.prices.get("night_coeff", 1.5)
        return round(p, 2)
    def send_msg(self, uid, text, keyboard=None):
        try:
            self.vk.messages.send(user_id=uid, message=str(text), random_id=get_random_id(), keyboard=keyboard)
            return True
        except Exception as e:
            log_error(f"Send error {uid}: {e}")
            return False
    def send_chat_msg(self, peer_id, text, keyboard=None):
        try:
            self.vk.messages.send(peer_id=peer_id, message=str(text), random_id=get_random_id(), keyboard=keyboard)
        except Exception as e:
            log_error(f"Chat error {peer_id}: {e}")
    def notify_admins(self, text):
        for a in ADMIN_IDS: self.send_msg(a, f"🔔 {text}")
    def get_active_operators(self):
        act = [o for o in self.operators if str(o) in self.shifts and self.shifts[str(o)].get("online")]
        for a in ADMIN_IDS:
            if "operator" in self.admin_roles.get(a, set()) and str(a) in self.shifts and self.shifts[str(a)].get("online") and a not in act:
                act.append(a)
        return act
    def notify_operators(self, text, exclude=None):
        for o in self.get_active_operators():
            if o != exclude: self.send_msg(o, f"🔔 {text}")
    def is_driver_online(self, uid): return str(uid) in self.drivers and self.drivers[str(uid)].get("online", False)
    def get_user_name(self, uid):
        if uid in ADMIN_IDS: return f"Админ {uid}"
        if str(uid) in self.drivers: return self.drivers[str(uid)].get("name", "?")
        return f"ID:{uid}"

    def kb_address_choice(self, count):
        kb = VkKeyboard(one_time=False, inline=False)
        for i in range(1, count+1): kb.add_button(str(i), color=VkKeyboardColor.PRIMARY)
        kb.add_line()
        kb.add_button("✏️ Другой адрес", color=VkKeyboardColor.SECONDARY)
        kb.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
        return kb.get_keyboard()

    def kb_address_not_found(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("✏️ Попробовать снова", color=VkKeyboardColor.PRIMARY)
        kb.add_line()
        kb.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
        return kb.get_keyboard()

    def calculate_route_for_temp(self, uid):
        temp = self.temp[str(uid)]
        coords = []
        for addr in temp.get("points", []):
            lat, lon = get_coordinates(addr)
            if lat and lon: coords.append((lat, lon))
        km, dur = get_route_multi(coords) if len(coords) >= 2 else (0, 0)
        temp["km"], temp["duration"], temp["price"] = km, dur, self.calculate_price(km)
        temp["night_coeff_applied"] = is_night_time()

    def show_route_summary(self, uid):
        t = self.temp[str(uid)]
        pts, km, dur, price = t.get("points",[]), t.get("km",0), t.get("duration",0), t.get("price",0)
        night = " 🌙 НОЧНОЙ ТАРИФ" if t.get("night_coeff_applied") else ""
        ptxt = f"{price}₽" if price > 0 else "уточняется"
        route = pts[0] if pts else "?"
        for p in pts[1:]: route += f" → {p}"
        t["route_str"] = route
        can = len(pts) < 5
        txt = f"📋 Маршрут{night}\n\n📍 {route}\n📏 {km} км | ⏱ {dur} мин | 💰 {ptxt}\n"
        kb = VkKeyboard(one_time=False, inline=False)
        if can:
            txt += f"\nДобавить ещё точку? (макс. 5)"
            kb.add_button("➕ Добавить точку", color=VkKeyboardColor.PRIMARY)
            kb.add_button("✅ Завершить маршрут", color=VkKeyboardColor.POSITIVE)
        else:
            txt += "\nДостигнут максимум точек."
            kb.add_button("✅ Завершить маршрут", color=VkKeyboardColor.POSITIVE)
        kb.add_line()
        kb.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
        self.send_msg(uid, txt, kb.get_keyboard())

    def kb_client(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("🚕 Заказать такси", color=VkKeyboardColor.PRIMARY)
        kb.add_button("📞 Перезвоните мне", color=VkKeyboardColor.POSITIVE)
        return kb.get_keyboard()
    def kb_admin_main(self, uid):
        roles = self.admin_roles.get(uid, set())
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button(f"📞 Оператор {'✅' if 'operator' in roles else ''}", color=VkKeyboardColor.PRIMARY)
        kb.add_button(f"🚗 Водитель {'✅' if 'driver' in roles else ''}", color=VkKeyboardColor.PRIMARY)
        kb.add_line()
        kb.add_button("⚙️ Управление таксопарком", color=VkKeyboardColor.SECONDARY)
        kb.add_line()
        kb.add_button("🔄 Обновить", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_admin_operator(self, uid):
        s = self.shifts.get(str(uid), {})
        kb = VkKeyboard(one_time=False, inline=False)
        if s.get("online"): kb.add_button("🏁 Завершить смену", color=VkKeyboardColor.NEGATIVE); kb.add_button("📋 Новый заказ", color=VkKeyboardColor.PRIMARY)
        else: kb.add_button("✅ Начать смену", color=VkKeyboardColor.POSITIVE)
        kb.add_line(); kb.add_button("👤 Водители на линии", color=VkKeyboardColor.PRIMARY); kb.add_button("🔍 Поиск заказа", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("📞 Звонки клиентов", color=VkKeyboardColor.POSITIVE); kb.add_button("❌ Отменить заказ", color=VkKeyboardColor.NEGATIVE)
        kb.add_line(); kb.add_button("🔙 Выйти из роли", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_admin_driver(self, uid):
        s = str(uid); o = self.is_driver_online(uid)
        kb = VkKeyboard(one_time=False, inline=False)
        if o:
            kb.add_button("🔴 Уйти с линии", color=VkKeyboardColor.NEGATIVE)
            if s in self.driver_current_order: kb.add_button("✅ Завершить заказ", color=VkKeyboardColor.POSITIVE)
            elif self.pending_orders: kb.add_button("📋 Доступные заказы", color=VkKeyboardColor.PRIMARY)
            else: kb.add_button("🔄 Обновить", color=VkKeyboardColor.SECONDARY)
        else: kb.add_button("🟢 Выйти на линию", color=VkKeyboardColor.POSITIVE)
        kb.add_line(); kb.add_button("🔙 Выйти из роли", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_admin_panel(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("👥 Сотрудники", color=VkKeyboardColor.PRIMARY); kb.add_button("📝 Тарифы", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("💬 Сообщения", color=VkKeyboardColor.PRIMARY); kb.add_button("📋 Заказы", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("📞 Обратные звонки", color=VkKeyboardColor.POSITIVE)
        kb.add_line(); kb.add_button("🔙 Главное меню", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_staff_menu(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("➕ Добавить водителя", color=VkKeyboardColor.PRIMARY); kb.add_button("➕ Добавить оператора", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("➖ Удалить сотрудника", color=VkKeyboardColor.NEGATIVE)
        kb.add_line(); kb.add_button("🔙 Назад в управление", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_messages_menu(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("👋 Приветствие в чате", color=VkKeyboardColor.PRIMARY); kb.add_button("🚪 Прощание из чата", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("🚕 Сообщение заказа", color=VkKeyboardColor.PRIMARY); kb.add_button("⚠️ Ошибка ЛС", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("📞 Номер телефона", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("🔙 Назад в управление", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_orders_menu(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("📋 Все заказы", color=VkKeyboardColor.PRIMARY); kb.add_button("🔍 Поиск заказа", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("❌ Отменить заказ", color=VkKeyboardColor.NEGATIVE)
        kb.add_line(); kb.add_button("🔙 Назад в управление", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_operator(self, uid):
        s = self.shifts.get(str(uid), {})
        kb = VkKeyboard(one_time=False, inline=False)
        if s.get("online"): kb.add_button("🏁 Завершить смену", color=VkKeyboardColor.NEGATIVE); kb.add_button("📋 Новый заказ", color=VkKeyboardColor.PRIMARY)
        else: kb.add_button("✅ Начать смену", color=VkKeyboardColor.POSITIVE)
        kb.add_line(); kb.add_button("👤 Водители на линии", color=VkKeyboardColor.PRIMARY); kb.add_button("🔍 Поиск заказа", color=VkKeyboardColor.PRIMARY)
        kb.add_line(); kb.add_button("📞 Звонки клиентов", color=VkKeyboardColor.POSITIVE); kb.add_button("❌ Отменить заказ", color=VkKeyboardColor.NEGATIVE)
        return kb.get_keyboard()
    def kb_driver(self, uid):
        s = str(uid); o = self.is_driver_online(uid)
        kb = VkKeyboard(one_time=False, inline=False)
        if o:
            kb.add_button("🔴 Уйти с линии", color=VkKeyboardColor.NEGATIVE)
            if s in self.driver_current_order: kb.add_button("✅ Завершить заказ", color=VkKeyboardColor.POSITIVE)
            elif self.pending_orders: kb.add_button("📋 Доступные заказы", color=VkKeyboardColor.PRIMARY)
            else: kb.add_button("🔄 Обновить", color=VkKeyboardColor.SECONDARY)
        else: kb.add_button("🟢 Выйти на линию", color=VkKeyboardColor.POSITIVE)
        kb.add_line(); kb.add_button("🔄 Обновить", color=VkKeyboardColor.SECONDARY)
        return kb.get_keyboard()
    def kb_cancel(self):
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
        return kb.get_keyboard()
    def kb_back_to_admin(self):
        kb = VkKeyboard(one_time=False, inline=False)
        kb.add_button("🔙 Назад в админку", color=VkKeyboardColor.SECONDARY); kb.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
        return kb.get_keyboard()

    def handle_chat_join(self, peer_id, uid): self.send_chat_msg(peer_id, f"@id{uid}, {self.get_msg('welcome_msg')}")
    def handle_chat_leave(self, peer_id, uid): self.send_chat_msg(peer_id, self.get_msg('goodbye_msg'))
    def handle_chat_message(self, peer_id, uid, text):
        if text.strip().lower() in ["!такси", "такси", "заказать такси"]:
            self.send_chat_msg(peer_id, self.get_msg("order_msg"))
            if not self.send_msg(uid, f"🚕 Здравствуйте!\n\nДля заказа такси нажмите кнопку ниже или позвоните:\n📞 {self.phone}", self.kb_client()):
                self.send_chat_msg(peer_id, self.get_msg("ls_error_msg", user_id=uid))

    def client_menu(self, uid): self.send_msg(uid, f"🚕 Добро пожаловать!\n\nДля заказа такси нажмите кнопку ниже или позвоните:\n📞 {self.phone}", self.kb_client())
    def client_order_taxi_start(self, uid):
        self.states[uid] = "route_phone"
        self.temp[str(uid)] = {"created_by_client": True, "operator_id": uid, "points": []}
        self.send_msg(uid, "📞 Введите ваш номер телефона:", self.kb_cancel())
    def callback_request(self, uid):
        self.states[uid] = "callback_phone"; self.send_msg(uid, "📞 Введите номер телефона:", self.kb_cancel())
    def callback_save(self, uid, phone):
        self.callbacks.append({"id": len(self.callbacks)+1, "user_id": uid, "phone": phone, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "new"})
        save_json(CALLBACKS_FILE, self.callbacks)
        self.notify_operators(f"📞 Новый звонок!\n📱 {phone}")
        self.send_msg(uid, f"✅ Заявка принята!\n📱 {phone}", self.kb_client())
        del self.states[uid]
    def show_callbacks(self, uid):
        new_cb = [c for c in self.callbacks if c.get("status") == "new"]
        if not new_cb: self.send_msg(uid, "📭 Нет заявок."); return
        txt = "📞 ЗАЯВКИ:\n\n"
        for cb in new_cb: txt += f"#{cb['id']} | 📱 {cb['phone']} | 🕐 {cb['created_at']}\n"
        txt += "\nОтметить: «звонок НОМЕР»"
        self.states[uid] = "callback_done"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔙 Назад", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, txt, kb.get_keyboard())
    def callback_done(self, uid, cid):
        try:
            cid = int(cid)
            for cb in self.callbacks:
                if cb["id"] == cid and cb["status"] == "new":
                    cb["status"] = "done"; cb["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_json(CALLBACKS_FILE, self.callbacks)
                    self.send_msg(uid, f"✅ #{cid} обработана!"); return
            self.send_msg(uid, f"❌ #{cid} не найдена.")
        except: self.send_msg(uid, "❌ Формат: звонок 1")

    def admin_messages_menu(self, uid): self.send_msg(uid, "💬 Управление сообщениями", self.kb_messages_menu())
    def admin_edit_welcome(self, uid):
        self.states[uid] = "edit_welcome"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔄 Сбросить", color=VkKeyboardColor.NEGATIVE); kb.add_button("🔙 Назад к сообщениям", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, f"👋 ПРИВЕТСТВИЕ\n\nТекущее:\n{self.get_msg('welcome_msg')}\n\nНовый текст:", kb.get_keyboard())
    def admin_edit_goodbye(self, uid):
        self.states[uid] = "edit_goodbye"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔄 Сбросить", color=VkKeyboardColor.NEGATIVE); kb.add_button("🔙 Назад к сообщениям", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, f"🚪 ПРОЩАНИЕ\n\nТекущее:\n{self.get_msg('goodbye_msg')}\n\nНовый текст:", kb.get_keyboard())
    def admin_edit_order(self, uid):
        self.states[uid] = "edit_order"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔄 Сбросить", color=VkKeyboardColor.NEGATIVE); kb.add_button("🔙 Назад к сообщениям", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, f"🚕 СООБЩЕНИЕ ЗАКАЗА\n\nТекущее:\n{self.get_msg('order_msg')}\n\nНовый текст:", kb.get_keyboard())
    def admin_edit_ls_error(self, uid):
        self.states[uid] = "edit_ls_error"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔄 Сбросить", color=VkKeyboardColor.NEGATIVE); kb.add_button("🔙 Назад к сообщениям", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, f"⚠️ ОШИБКА ЛС\n\nТекущее:\n{self.get_msg('ls_error_msg', user_id='123')}\n\nНовый текст:", kb.get_keyboard())
    def admin_edit_phone(self, uid):
        self.states[uid] = "edit_phone"
        kb = VkKeyboard(one_time=False, inline=False); kb.add_button("🔄 Сбросить", color=VkKeyboardColor.NEGATIVE); kb.add_button("🔙 Назад к сообщениям", color=VkKeyboardColor.SECONDARY)
        self.send_msg(uid, f"📞 НОМЕР\n\nТекущий: {self.phone}\n\nНовый номер:", kb.get_keyboard())
    def admin_save_message(self, uid, msg_type, text):
        defaults = {"welcome_msg": DEFAULT_WELCOME, "goodbye_msg": DEFAULT_GOODBYE, "order_msg": DEFAULT_ORDER_MSG, "ls_error_msg": DEFAULT_LS_ERROR_MSG}
        self.settings[msg_type] = defaults[msg_type] if text in ["🔄 Сбросить", "сброс"] else text
        save_json(SETTINGS_FILE, self.settings)
        self.send_msg(uid, "✅ Сохранено!", self.kb_messages_menu())
        del self.states[uid]
    def admin_save_phone(self, uid, text):
        self.phone = DEFAULT_PHONE if text in ["🔄 Сбросить", "сброс"] else text
        self.settings["phone"] = self.phone
        save_json(SETTINGS_FILE, self.settings)
        self.send_msg(uid, f"✅ Номер: {self.phone}", self.kb_messages_menu())
        del self.states[uid]

    def admin_main_menu(self, uid): self.send_msg(uid, "👑 Главное меню", self.kb_admin_main(uid))
    def admin_enter_operator(self, uid): self.admin_roles[uid].add("operator"); self.send_msg(uid, "📞 Оператор", self.kb_admin_operator(uid))
    def admin_enter_driver(self, uid):
        s = str(uid)
        if s not in self.drivers:
            self.drivers[s] = {"name": f"Админ {uid}", "car": "Личный авто", "phone": "+7 (XXX) XXX-XX-XX", "online": False}
            save_json(DRIVERS_FILE, self.drivers)
        self.admin_roles[uid].add("driver"); self.send_msg(uid, "🚗 Водитель", self.kb_admin_driver(uid))
    def admin_exit_role(self, uid): self.admin_roles[uid].clear(); self.admin_main_menu(uid)
    def admin_panel(self, uid): self.send_msg(uid, "⚙️ Управление таксопарком", self.kb_admin_panel())
    def admin_staff_menu(self, uid): self.send_msg(uid, "👥 Сотрудники", self.kb_staff_menu())
    def admin_orders_menu(self, uid): self.send_msg(uid, "📋 Заказы", self.kb_orders_menu())
    def admin_add_driver_start(self, uid):
        self.states[uid] = "add_driver_id"; self.temp[str(uid)] = {}
        self.send_msg(uid, "🆔 ID водителя ВК:", self.kb_back_to_admin())
    def admin_add_operator_start(self, uid):
        self.states[uid] = "add_operator_id"; self.send_msg(uid, "🆔 ID оператора ВК:", self.kb_back_to_admin())
    def admin_delete_menu(self, uid):
        txt = "🗑 Введите ID:\n\n🚗 Водители:\n"
        for did, info in self.drivers.items(): txt += f"  {did} - {info.get('name','?')} | 🚗 {info.get('car','?')}\n"
        txt += "\n📞 Операторы:\n"
        for oid in self.operators: txt += f"  {oid}\n"
        self.states[uid] = "delete_user"; self.send_msg(uid, txt, self.kb_back_to_admin())
    def admin_tariffs(self, uid):
        p = self.prices
        ns = "🌙 Ночной" if is_night_time() else "☀️ Дневной"
        txt = f"📝 ТАРИФЫ\n\n📏 Км: {p.get('price_per_km',25)}₽\n🌙 Ночной коэфф: x{p.get('night_coeff',1.5)}\n\n{ns}\n\n«км 30» «ночь 1.5» «сброс»"
        self.states[uid] = "change_tariff"; self.send_msg(uid, txt, self.kb_back_to_admin())
    def admin_operators_online(self, uid):
        ops = self.get_active_operators()
        if not ops: self.send_msg(uid, "😴 Нет операторов."); return
        txt = "📞 ОПЕРАТОРЫ НА ЛИНИИ:\n\n"
        for o in ops:
            s = self.shifts.get(str(o), {})
            txt += f"👤 {self.get_user_name(o)}\n📋 Заказов: {s.get('orders_count',0)}\n🕐 {s.get('start_time','—')}\n\n"
        self.send_msg(uid, txt)
    def admin_all_orders(self, uid):
        all_ord = list(load_json(ORDERS_FILE) or [])
        for oid, od in {**self.pending_orders, **self.active_orders}.items():
            if not any(o.get("order_id") == oid for o in all_ord): all_ord.append(od)
        for od in self.driver_current_order.values():
            if not any(o.get("order_id") == od.get("order_id") for o in all_ord): all_ord.append(od)
        if not all_ord: self.send_msg(uid, "📭 Нет заказов."); return
        txt = "📋 ВСЕ ЗАКАЗЫ:\n\n"
        for o in all_ord[-20:]:
            st = {"pending":"🟡","accepted":"🟢","completed":"✅","cancelled":"❌"}
            src = "👤" if o.get("created_by_client") else "📞"
            txt += f"#{o.get('order_id')} | {st.get(o.get('status'),'?')} | {src}\n📞 {o.get('client_phone','?')}\n📍 {o.get('address_from','?')} → {o.get('address_to','?')}\n📏 {o.get('km',0)}км | ⏱ {o.get('duration',0)}м | 💰 {o.get('price',0)}₽\n\n"
        self.send_msg(uid, txt)
    def cancel_order_start(self, uid):
        self.states[uid] = "cancel_order"
        txt = "❌ ОТМЕНА ЗАКАЗА\n\n"; has = False
        if self.active_orders:
            txt += "🟢 Активные:\n"
            for oid, od in self.active_orders.items(): txt += f"  #{oid} | 🚗 {od.get('driver_name','?')}\n"
            has = True
        if self.pending_orders:
            txt += "\n🟡 Ожидают:\n"
            for oid, od in self.pending_orders.items(): txt += f"  #{oid} | 💰 {od.get('price',0)}₽\n"
            has = True
        if self.driver_current_order:
            txt += "\n🔵 Выполняются:\n"
            for od in self.driver_current_order.values(): txt += f"  #{od.get('order_id')} | 🚗 {od.get('driver_name','?')}\n"
            has = True
        if not has: self.send_msg(uid, "📭 Нет заказов."); del self.states[uid]; return
        txt += "\nВведите номер заказа:"; self.send_msg(uid, txt, self.kb_cancel())
    def cancel_order_execute(self, uid, oid_text):
        try:
            oid = int(oid_text); cancelled = False; driver_id = None
            if oid in self.active_orders:
                od = self.active_orders[oid]; driver_id = od.get("driver_id")
                od["status"]="cancelled"; od["cancelled_by"]=uid; od["cancelled_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                orders = load_json(ORDERS_FILE) or []; orders.append(od); save_json(ORDERS_FILE, orders)
                del self.active_orders[oid]; cancelled = True
            elif oid in self.pending_orders:
                od = self.pending_orders[oid]
                od["status"]="cancelled"; od["cancelled_by"]=uid; od["cancelled_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                orders = load_json(ORDERS_FILE) or []; orders.append(od); save_json(ORDERS_FILE, orders)
                del self.pending_orders[oid]; cancelled = True
            else:
                for did, od in list(self.driver_current_order.items()):
                    if od.get("order_id") == oid:
                        driver_id = did; od["status"]="cancelled"; od["cancelled_by"]=uid; od["cancelled_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        orders = load_json(ORDERS_FILE) or []; orders.append(od); save_json(ORDERS_FILE, orders)
                        del self.driver_current_order[did]; cancelled = True; break
            if cancelled:
                if driver_id: self.send_msg(int(driver_id), f"❌ Заказ #{oid} отменён.")
                self.send_msg(uid, f"✅ Заказ #{oid} отменён.")
            else: self.send_msg(uid, f"❌ Заказ #{oid} не найден.")
        except: self.send_msg(uid, "❌ Ошибка.")
        del self.states[uid]

    def operator_start_shift(self, uid):
        s = str(uid); self.shifts[s] = {"start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "online": True, "orders_count": 0}
        save_json(SHIFTS_FILE, self.shifts)
        self.notify_admins(f"📞 {self.get_user_name(uid)} начал смену")
        self.send_msg(uid, "✅ Смена начата!", self.kb_admin_operator(uid) if self.is_admin(uid) else self.kb_operator(uid))
    def operator_end_shift(self, uid):
        s = str(uid)
        if s in self.shifts:
            orders = self.shifts[s].get("orders_count", 0); self.shifts[s]["online"] = False
            save_json(SHIFTS_FILE, self.shifts)
            self.send_msg(uid, f"🏁 Смена завершена!\n📋 Заказов: {orders}", self.kb_admin_operator(uid) if self.is_admin(uid) else self.kb_operator(uid))
        else: self.send_msg(uid, "⚠️ Смена не начата.")
    def operator_new_order(self, uid):
        self.states[uid] = "route_phone"
        self.temp[str(uid)] = {"operator_id": uid, "created_by_client": False, "points": []}
        self.send_msg(uid, "📞 Номер телефона клиента:", self.kb_cancel())
    def operator_drivers_online(self, uid):
        online = {k:v for k,v in self.drivers.items() if v.get("online")}
        busy = set(); busy.update(str(od.get("driver_id")) for od in self.active_orders.values()); busy.update(self.driver_current_order.keys())
        if not online: self.send_msg(uid, "😴 Нет водителей."); return
        txt = "👤 ВОДИТЕЛИ:\n\n"
        for did, info in online.items(): txt += f"🚗 {info.get('name','?')} | {info.get('car','?')} {'🔴' if did in busy else '🟢'}\n"
        self.send_msg(uid, txt)
    def publish_order_to_drivers(self, od):
        oid = od["order_id"]
        free = {k:v for k,v in self.drivers.items() if v.get("online") and k not in self.driver_current_order}
        if not free: return False
        self.pending_orders[oid] = od
        src = "👤 Клиент" if od.get("created_by_client") else "📞 Оператор"
        night = " 🌙 НОЧНОЙ" if od.get("night_coeff_applied") else ""
        pts = od.get("route_str", f"{od.get('address_from','?')} → {od.get('address_to','?')}")
        txt = f"📋 {src} ЗАКАЗ #{oid}{night}\n\n📞 {od.get('client_phone','?')}\n📍 {pts}\n📏 {od.get('km',0)} км | ⏱ {od.get('duration',0)} мин | 💰 {od['price']}₽\n\n«📋 Доступные заказы»"
        for did in free: self.send_msg(int(did), txt)
        return True

    def driver_go_online(self, uid):
        s = str(uid)
        if s not in self.drivers: self.send_msg(uid, "❌ Вы не водитель."); return
        self.drivers[s]["online"] = True; save_json(DRIVERS_FILE, self.drivers)
        name = self.drivers[s].get("name","?")
        self.notify_admins(f"🟢 Водитель {name} на линии"); self.notify_operators(f"🟢 Водитель {name} на линии")
        self.send_msg(uid, "🟢 Вы на линии!", self.kb_admin_driver(uid) if self.is_admin(uid) else self.kb_driver(uid))
    def driver_go_offline(self, uid):
        s = str(uid)
        if s in self.driver_current_order: self.send_msg(uid, "⚠️ Сначала завершите заказ!"); return
        self.drivers[s]["online"] = False; save_json(DRIVERS_FILE, self.drivers)
        self.notify_admins(f"🔴 Водитель {self.drivers[s].get('name','?')} ушёл")
        self.send_msg(uid, "🔴 Вы ушли с линии.", self.kb_admin_driver(uid) if self.is_admin(uid) else self.kb_driver(uid))
    def driver_show_orders(self, uid):
        if not self.pending_orders:
            self.send_msg(uid, "📭 Нет заказов.", self.kb_admin_driver(uid) if self.is_admin(uid) else self.kb_driver(uid)); return
        kb = VkKeyboard(one_time=False, inline=False)
        for oid in self.pending_orders: kb.add_button(f"✅ Взять #{oid}", color=VkKeyboardColor.POSITIVE); kb.add_line()
        kb.add_button("🔄 Обновить", color=VkKeyboardColor.SECONDARY)
        txt = "📋 ДОСТУПНЫЕ ЗАКАЗЫ:\n\n"
        for oid, od in self.pending_orders.items():
            src = "👤" if od.get("created_by_client") else "📞"; night = " 🌙" if od.get("night_coeff_applied") else ""
            txt += f"#{oid} | {src}{night}\n📞 {od.get('client_phone','?')}\n📍 {od.get('route_str','?')}\n📏 {od.get('km',0)} км | 💰 {od['price']}₽\n\n"
        self.send_msg(uid, txt, kb.get_keyboard())
    def driver_accept_order(self, driver_id, oid):
        if oid not in self.pending_orders: self.send_msg(driver_id, "❌ Заказ недоступен."); return
        s = str(driver_id); od = self.pending_orders[oid]; op_id = od.get("operator_id")
        od["driver_id"] = driver_id; od["driver_name"] = self.drivers[s].get("name","?"); od["driver_car"] = self.drivers[s].get("car","?")
        od["status"] = "accepted"; od["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.driver_current_order[s] = od; del self.pending_orders[oid]
        self.send_msg(op_id, f"✅ {od['driver_name']} принял заказ #{oid}!", self.kb_admin_operator(op_id) if self.is_admin(op_id) else self.kb_operator(op_id))
        self.send_msg(driver_id, f"✅ Заказ #{oid} принят!\n📞 {od.get('client_phone','?')}\n«✅ Завершить заказ»", self.kb_admin_driver(driver_id) if self.is_admin(driver_id) else self.kb_driver(driver_id))
        if od.get("created_by_client"): self.send_msg(od.get("operator_id"), f"🚕 Водитель принял ваш заказ #{oid}!\n\n👤 {od['driver_name']}\n🚗 {od['driver_car']}\n\nОжидайте.")
        if not od.get("created_by_client") and str(op_id) in self.shifts:
            self.shifts[str(op_id)]["orders_count"] = self.shifts[str(op_id)].get("orders_count",0) + 1
            save_json(SHIFTS_FILE, self.shifts)
        for did, info in self.drivers.items():
            if info.get("online") and did != s: self.send_msg(int(did), f"🔔 Заказ #{oid} забрал {od['driver_name']}")
    def complete_order(self, driver_id):
        s = str(driver_id)
        if s not in self.driver_current_order: self.send_msg(driver_id, "❌ Нет активного заказа."); return
        od = self.driver_current_order[s]; oid = od["order_id"]; op_id = od.get("operator_id")
        od["status"] = "completed"; od["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        orders = load_json(ORDERS_FILE) or []; orders.append(od); save_json(ORDERS_FILE, orders)
        del self.driver_current_order[s]
        self.notify_admins(f"✅ Заказ #{oid} выполнен!")
        if op_id and op_id != driver_id: self.send_msg(op_id, f"✅ Заказ #{oid} выполнен!\n💰 {od.get('price',0)}₽", self.kb_admin_operator(op_id) if self.is_admin(op_id) else self.kb_operator(op_id))
        self.send_msg(driver_id, f"✅ Заказ #{oid} завершён!\nВы на линии.", self.kb_admin_driver(driver_id) if self.is_admin(driver_id) else self.kb_driver(driver_id))

    def show_order_info(self, uid, oid_text):
        try:
            oid = int(oid_text)
            found = self.pending_orders.get(oid) or self.active_orders.get(oid)
            if not found:
                for od in self.driver_current_order.values():
                    if od.get("order_id") == oid: found = od; break
            if not found:
                for o in (load_json(ORDERS_FILE) or []):
                    if o.get("order_id") == oid: found = o; break
            if found:
                st = {"pending":"🟡","accepted":"🟢","completed":"✅","cancelled":"❌"}
                txt = f"🔍 ЗАКАЗ #{oid}\n\n📞 {found.get('client_phone','?')}\n📍 {found.get('route_str','?')}\n📏 {found.get('km',0)} км | ⏱ {found.get('duration',0)} мин | 💰 {found.get('price',0)}₽\n🚗 {found.get('driver_name','?')}\n📌 {st.get(found.get('status'),'?')}"
            else: txt = f"❌ Заказ #{oid} не найден."
        except: txt = "❌ Ошибка."
        self.send_msg(uid, txt)

    def handle_ls(self, uid, text):
        try:
            state = self.states.get(uid)
            if text.lower() == "!ping": self.send_msg(uid, "🟢 Бот работает!"); return
            if text in ["🔄 Обновить", "🔄 Обновить меню"]:
                if uid in self.states: del self.states[uid]
                if str(uid) in self.temp: del self.temp[str(uid)]
                if self.is_admin(uid): self.admin_main_menu(uid)
                elif uid in self.operators: self.send_msg(uid, "📞 Меню оператора", self.kb_operator(uid))
                elif str(uid) in self.drivers: self.send_msg(uid, "🚗 Меню водителя", self.kb_driver(uid))
                else: self.client_menu(uid)
                return
            if text == "❌ Отмена":
                if uid in self.states: del self.states[uid]
                if str(uid) in self.temp: del self.temp[str(uid)]
                if self.is_admin(uid): self.admin_main_menu(uid)
                elif uid in self.operators: self.send_msg(uid, "📞 Меню оператора", self.kb_operator(uid))
                elif str(uid) in self.drivers: self.send_msg(uid, "🚗 Меню водителя", self.kb_driver(uid))
                else: self.client_menu(uid)
                return
            if text in ["🔙 Назад в админку", "🔙 Назад в управление"]:
                if uid in self.states: del self.states[uid]
                self.admin_panel(uid); return
            if text == "🔙 Назад к сообщениям":
                if uid in self.states: del self.states[uid]
                self.admin_messages_menu(uid); return
            if text in ["🔙 Выйти из роли", "🔙 Назад"]:
                if uid in self.states: del self.states[uid]
                self.admin_exit_role(uid); return

            if state == "callback_phone": self.callback_save(uid, text.strip())
            elif state == "callback_done":
                if text.lower().startswith("звонок"): self.callback_done(uid, text.replace("звонок","").strip())
                del self.states[uid]
            elif state == "cancel_order": self.cancel_order_execute(uid, text)
            elif state == "edit_welcome": self.admin_save_message(uid, "welcome_msg", text)
            elif state == "edit_goodbye": self.admin_save_message(uid, "goodbye_msg", text)
            elif state == "edit_order": self.admin_save_message(uid, "order_msg", text)
            elif state == "edit_ls_error": self.admin_save_message(uid, "ls_error_msg", text)
            elif state == "edit_phone": self.admin_save_phone(uid, text)

            elif state == "route_phone":
                self.temp[str(uid)]["client_phone"] = text.strip()
                self.states[uid] = "route_first_point"
                self.send_msg(uid, "📍 Введите адрес подачи:", self.kb_cancel())

            elif state == "route_first_point":
                suggestions = suggest_address(text)
                if suggestions:
                    self.temp[str(uid)]["suggestions_first"] = suggestions
                    txt = "🔍 Уточните адрес:\n\n"
                    for i, addr in enumerate(suggestions, 1): txt += f"{i}. {addr}\n"
                    txt += "\nНажмите цифру нужного адреса:"
                    self.send_msg(uid, txt, self.kb_address_choice(len(suggestions)))
                    self.states[uid] = "route_first_point_select"
                else:
                    self.send_msg(uid, "❌ Адрес не найден.", self.kb_address_not_found())
                    self.states[uid] = "route_first_point_retry"

            elif state == "route_first_point_select":
                suggestions = self.temp.get(str(uid), {}).get("suggestions_first", [])
                if text.isdigit():
                    idx = int(text) - 1
                    if 0 <= idx < len(suggestions):
                        self.temp[str(uid)]["points"] = [suggestions[idx]]
                        self.temp[str(uid)]["address_from"] = suggestions[idx]
                        self.states[uid] = "route_next_point"
                        self.send_msg(uid, f"✅ Адрес подачи: {suggestions[idx]}\n\n🎯 Введите адрес назначения:", self.kb_cancel())
                        return
                if text == "✏️ Другой адрес":
                    self.states[uid] = "route_first_point"
                    self.send_msg(uid, "📍 Введите адрес подачи:", self.kb_cancel())
                elif text == "❌ Отмена":
                    self.send_msg(uid, "❌ Отменено.", self.kb_client() if self.temp.get(str(uid),{}).get("created_by_client") else self.kb_operator(uid))
                    del self.states[uid]
                else: self.send_msg(uid, "Пожалуйста, нажмите цифру нужного адреса.")

            elif state == "route_first_point_retry":
                if text == "✏️ Попробовать снова":
                    self.states[uid] = "route_first_point"
                    self.send_msg(uid, "📍 Введите адрес подачи:", self.kb_cancel())
                elif text == "❌ Отмена":
                    self.send_msg(uid, "❌ Отменено.", self.kb_client() if self.temp.get(str(uid),{}).get("created_by_client") else self.kb_operator(uid))
                    del self.states[uid]

            elif state == "route_next_point":
                point_idx = len(self.temp[str(uid)].get("points", []))
                suggestions = suggest_address(text)
                if suggestions:
                    self.temp[str(uid)][f"suggestions_point_{point_idx}"] = suggestions
                    txt = "🔍 Уточните адрес:\n\n"
                    for i, addr in enumerate(suggestions, 1): txt += f"{i}. {addr}\n"
                    txt += "\nНажмите цифру нужного адреса:"
                    self.send_msg(uid, txt, self.kb_address_choice(len(suggestions)))
                    self.states[uid] = "route_next_point_select"
                else:
                    self.send_msg(uid, "❌ Адрес не найден.", self.kb_address_not_found())
                    self.states[uid] = "route_next_point_retry"

            elif state == "route_next_point_select":
                point_idx = len(self.temp[str(uid)].get("points", []))
                suggestions = self.temp.get(str(uid), {}).get(f"suggestions_point_{point_idx}", [])
                if text.isdigit():
                    idx = int(text) - 1
                    if 0 <= idx < len(suggestions):
                        temp = self.temp[str(uid)]
                        temp["points"].append(suggestions[idx])
                        if len(temp["points"]) == 2: temp["address_to"] = suggestions[idx]
                        else: temp["address_to"] = temp.get("address_to", "") + f" → {suggestions[idx]}"
                        self.calculate_route_for_temp(uid)
                        self.states[uid] = "route_summary"
                        self.show_route_summary(uid)
                        return
                if text == "✏️ Другой адрес":
                    self.states[uid] = "route_next_point"
                    self.send_msg(uid, "📍 Введите адрес:", self.kb_cancel())
                elif text == "❌ Отмена":
                    self.send_msg(uid, "❌ Отменено.", self.kb_client() if self.temp.get(str(uid),{}).get("created_by_client") else self.kb_operator(uid))
                    del self.states[uid]
                else: self.send_msg(uid, "Пожалуйста, нажмите цифру нужного адреса.")

            elif state == "route_next_point_retry":
                if text == "✏️ Попробовать снова":
                    self.states[uid] = "route_next_point"
                    self.send_msg(uid, "📍 Введите адрес:", self.kb_cancel())
                elif text == "❌ Отмена":
                    self.send_msg(uid, "❌ Отменено.", self.kb_client() if self.temp.get(str(uid),{}).get("created_by_client") else self.kb_operator(uid))
                    del self.states[uid]

            elif state == "route_summary":
                temp = self.temp[str(uid)]
                if text == "➕ Добавить точку":
                    if len(temp.get("points",[])) >= 5: self.send_msg(uid, "❌ Максимум 5 точек!")
                    else:
                        self.states[uid] = "route_next_point"
                        self.send_msg(uid, f"📍 Введите адрес точки #{len(temp['points'])+1}:", self.kb_cancel())
                elif text == "✅ Завершить маршрут":
                    is_client = temp.get("created_by_client", False)
                    if is_client:
                        self.states[uid] = "client_confirm_price"
                        night = " 🌙 НОЧНОЙ ТАРИФ" if temp.get("night_coeff_applied") else ""
                        ptxt = f"{temp.get('price',0)}₽" if temp.get('price',0) > 0 else "уточняется"
                        kb = VkKeyboard(one_time=False, inline=False)
                        kb.add_button("✅ Подтвердить заказ", color=VkKeyboardColor.POSITIVE)
                        kb.add_button("❌ Отменить", color=VkKeyboardColor.NEGATIVE)
                        self.send_msg(uid, f"📋 Заказ{night}\n\n📍 {temp.get('route_str','?')}\n📏 {temp.get('km',0)} км | ⏱ {temp.get('duration',0)} мин | 💰 {ptxt}\n\nПодтверждаете заказ?", kb.get_keyboard())
                    else:
                        oid = get_next_order_id()
                        od = {"order_id":oid,"client_phone":temp.get("client_phone",""),"address_from":temp.get("address_from",""),"address_to":temp.get("address_to",""),"points":temp.get("points",[]),"route_str":temp.get("route_str",""),"km":temp.get("km",0),"duration":temp.get("duration",0),"price":temp.get("price",0),"night_coeff_applied":temp.get("night_coeff_applied",False),"operator_id":uid,"created_by_client":False,"status":"pending"}
                        temp["order_data"] = od
                        self.states[uid] = "order_confirm_price"
                        night = " 🌙 НОЧНОЙ ТАРИФ" if temp.get("night_coeff_applied") else ""
                        self.send_msg(uid, f"📋 Заказ #{oid}{night}\n📞 {od['client_phone']}\n📍 {od['route_str']}\n📏 {od['km']} км | ⏱ {od['duration']} мин | 💰 {od['price']}₽\n\nНовая цена или «Ок»:", self.kb_cancel())
                elif text == "❌ Отмена":
                    kb = self.kb_client() if temp.get("created_by_client") else (self.kb_operator(uid) if not self.is_admin(uid) else self.kb_admin_operator(uid))
                    self.send_msg(uid, "❌ Маршрут отменён.", kb); del self.states[uid]

            elif state == "client_confirm_price":
                temp = self.temp[str(uid)]
                if text == "✅ Подтвердить заказ":
                    oid = get_next_order_id()
                    od = {"order_id":oid,"client_phone":temp.get("client_phone",""),"address_from":temp.get("address_from",""),"address_to":temp.get("address_to",""),"points":temp.get("points",[]),"route_str":temp.get("route_str",""),"km":temp.get("km",0),"duration":temp.get("duration",0),"price":temp.get("price",0),"night_coeff_applied":temp.get("night_coeff_applied",False),"operator_id":uid,"created_by_client":True,"status":"pending"}
                    online = {k:v for k,v in self.drivers.items() if v.get("online") and k not in self.driver_current_order}
                    ptxt = f"{od['price']}₽" if od['price'] > 0 else "уточняется"; night = " 🌙 НОЧНОЙ" if od.get("night_coeff_applied") else ""
                    if not online:
                        self.pending_orders[oid] = od
                        self.send_msg(uid, f"📋 Заказ #{oid} оформлен!{night}\n\n📞 {od['client_phone']}\n📍 {od['route_str']}\n📏 {od['km']} км | ⏱ {od['duration']} мин | 💰 {ptxt}\n\n🔍 Ищем машину...", self.kb_client())
                    else:
                        self.publish_order_to_drivers(od)
                        self.notify_operators(f"👤 Клиент оформил заказ #{oid}!\n📞 {od['client_phone']}\n📍 {od['route_str']}\n📏 {od['km']} км | 💰 {ptxt}")
                        self.send_msg(uid, f"📋 Заказ #{oid} оформлен!{night}\n\n📞 {od['client_phone']}\n📍 {od['route_str']}\n📏 {od['km']} км | ⏱ {od['duration']} мин | 💰 {ptxt}\n\n🔍 Ищем машину...", self.kb_client())
                    del self.states[uid]
                elif text == "❌ Отменить": self.send_msg(uid, "❌ Заказ отменён.", self.kb_client()); del self.states[uid]

            elif state == "order_confirm_price":
                try:
                    np = float(text.replace(",","."))
                    if np > 0: self.temp[str(uid)]["order_data"]["price"] = np
                except: pass
                od = self.temp[str(uid)]["order_data"]; oid = od["order_id"]
                online = {k:v for k,v in self.drivers.items() if v.get("online") and k not in self.driver_current_order}
                if not online:
                    self.pending_orders[oid] = od
                    self.send_msg(uid, "❌ Нет свободных водителей! Заказ сохранён."); del self.states[uid]; return
                self.publish_order_to_drivers(od)
                self.send_msg(uid, f"✅ Заказ #{oid} опубликован!\n💰 {od['price']}₽"); del self.states[uid]

            elif state in ["search_order","admin_search_order"]: self.show_order_info(uid, text); del self.states[uid]
            elif state == "add_driver_id":
                try:
                    driver_id = int(text.strip()); self.temp[str(uid)]["driver_id"] = str(driver_id)
                    self.states[uid] = "add_driver_car"; self.send_msg(uid, "🚗 Марка и номер авто:", self.kb_back_to_admin())
                except: self.send_msg(uid, "❌ ID должен быть числом!")
            elif state == "add_driver_car": self.temp[str(uid)]["car"] = text; self.states[uid] = "add_driver_name"; self.send_msg(uid, "👤 ФИО водителя:", self.kb_back_to_admin())
            elif state == "add_driver_name": self.temp[str(uid)]["name"] = text; self.states[uid] = "add_driver_phone"; self.send_msg(uid, "📞 Телефон:", self.kb_back_to_admin())
            elif state == "add_driver_phone":
                temp = self.temp[str(uid)]
                self.drivers[temp["driver_id"]] = {"name":temp["name"],"car":temp["car"],"phone":text,"online":False}
                save_json(DRIVERS_FILE, self.drivers)
                self.send_msg(uid, f"✅ Водитель {temp['name']} добавлен!", self.kb_staff_menu()); del self.states[uid]
            elif state == "add_operator_id":
                try:
                    new_id = int(text)
                    if new_id not in self.operators: self.operators.append(new_id); save_json(OPERATORS_FILE, self.operators)
                    self.send_msg(uid, f"✅ Оператор {new_id} добавлен!", self.kb_staff_menu())
                except: self.send_msg(uid, "❌ Неверный ID!")
                del self.states[uid]
            elif state == "delete_user":
                try:
                    did = text.strip(); deleted = False
                    if did in self.drivers: del self.drivers[did]; save_json(DRIVERS_FILE, self.drivers); deleted = True
                    if did.isdigit() and int(did) in self.operators and int(did) not in ADMIN_IDS: self.operators.remove(int(did)); save_json(OPERATORS_FILE, self.operators); deleted = True
                    self.send_msg(uid, f"{'✅ Удален' if deleted else '❌ Не найден'}!", self.kb_staff_menu())
                except: self.send_msg(uid, "❌ Ошибка!")
                del self.states[uid]
            elif state == "change_tariff":
                if text == "сброс":
                    self.prices = {"price_per_km": 25.0, "night_coeff": 1.5}; save_json(PRICES_FILE, self.prices)
                    self.send_msg(uid, "✅ Тарифы сброшены!")
                else:
                    try:
                        p = text.lower().split()
                        if p[0] == "км": self.prices["price_per_km"] = float(p[1]); self.send_msg(uid, f"✅ Цена за км: {p[1]}₽")
                        elif p[0] == "ночь": self.prices["night_coeff"] = float(p[1]); self.send_msg(uid, f"✅ Ночной коэффициент: x{p[1]}")
                        save_json(PRICES_FILE, self.prices)
                    except: self.send_msg(uid, "❌ «км 30» или «ночь 1.5»")
                del self.states[uid]

            else:
                if self.is_admin(uid):
                    roles = self.admin_roles.get(uid, set())
                    if text.startswith("📞 Оператор"): self.admin_enter_operator(uid)
                    elif text.startswith("🚗 Водитель"): self.admin_enter_driver(uid)
                    elif text == "⚙️ Управление таксопарком": self.admin_panel(uid)
                    elif text == "🔙 Выйти из роли": self.admin_exit_role(uid)
                    elif "operator" in roles:
                        if text == "✅ Начать смену": self.operator_start_shift(uid)
                        elif text == "🏁 Завершить смену": self.operator_end_shift(uid)
                        elif text == "📋 Новый заказ": self.operator_new_order(uid)
                        elif text == "👤 Водители на линии": self.operator_drivers_online(uid)
                        elif text == "🔍 Поиск заказа": self.states[uid] = "search_order"; self.send_msg(uid, "🔍 Номер заказа:", self.kb_cancel())
                        elif text == "📞 Звонки клиентов": self.show_callbacks(uid)
                        elif text == "❌ Отменить заказ": self.cancel_order_start(uid)
                        else: self.send_msg(uid, "📞 Меню оператора", self.kb_admin_operator(uid))
                    elif "driver" in roles:
                        if text == "🟢 Выйти на линию": self.driver_go_online(uid)
                        elif text == "🔴 Уйти с линии": self.driver_go_offline(uid)
                        elif text == "✅ Завершить заказ": self.complete_order(uid)
                        elif text == "📋 Доступные заказы": self.driver_show_orders(uid)
                        elif text.startswith("✅ Взять #"): self.driver_accept_order(uid, int(text.replace("✅ Взять #","").strip()))
                        else: self.send_msg(uid, "🚗 Меню водителя", self.kb_admin_driver(uid))
                    else:
                        if text == "👥 Сотрудники": self.admin_staff_menu(uid)
                        elif text == "📝 Тарифы": self.admin_tariffs(uid)
                        elif text == "💬 Сообщения": self.admin_messages_menu(uid)
                        elif text == "📋 Заказы": self.admin_orders_menu(uid)
                        elif text == "👋 Приветствие в чате": self.admin_edit_welcome(uid)
                        elif text == "🚪 Прощание из чата": self.admin_edit_goodbye(uid)
                        elif text == "🚕 Сообщение заказа": self.admin_edit_order(uid)
                        elif text == "⚠️ Ошибка ЛС": self.admin_edit_ls_error(uid)
                        elif text == "📞 Номер телефона": self.admin_edit_phone(uid)
                        elif text == "📞 Операторы на линии": self.admin_operators_online(uid)
                        elif text == "📞 Обратные звонки": self.show_callbacks(uid)
                        elif text == "🔙 Главное меню": self.admin_main_menu(uid)
                        elif text == "➕ Добавить водителя": self.admin_add_driver_start(uid)
                        elif text == "➕ Добавить оператора": self.admin_add_operator_start(uid)
                        elif text == "➖ Удалить сотрудника": self.admin_delete_menu(uid)
                        elif text == "📋 Все заказы": self.admin_all_orders(uid)
                        else: self.admin_main_menu(uid)
                elif uid in self.operators:
                    if text == "✅ Начать смену": self.operator_start_shift(uid)
                    elif text == "🏁 Завершить смену": self.operator_end_shift(uid)
                    elif text == "📋 Новый заказ": self.operator_new_order(uid)
                    elif text == "👤 Водители на линии": self.operator_drivers_online(uid)
                    elif text == "🔍 Поиск заказа": self.states[uid] = "search_order"; self.send_msg(uid, "🔍 Номер заказа:", self.kb_cancel())
                    elif text == "📞 Звонки клиентов": self.show_callbacks(uid)
                    elif text == "❌ Отменить заказ": self.cancel_order_start(uid)
                    else: self.send_msg(uid, "📞 Меню оператора", self.kb_operator(uid))
                elif str(uid) in self.drivers:
                    if text == "🟢 Выйти на линию": self.driver_go_online(uid)
                    elif text == "🔴 Уйти с линии": self.driver_go_offline(uid)
                    elif text == "✅ Завершить заказ": self.complete_order(uid)
                    elif text == "📋 Доступные заказы": self.driver_show_orders(uid)
                    elif text.startswith("✅ Взять #"): self.driver_accept_order(uid, int(text.replace("✅ Взять #","").strip()))
                    else: self.send_msg(uid, "🚗 Меню водителя", self.kb_driver(uid))
                else:
                    if text == "🚕 Заказать такси": self.client_order_taxi_start(uid)
                    elif text == "📞 Перезвоните мне": self.callback_request(uid)
                    else: self.client_menu(uid)
        except Exception as e:
            log_error(f"LS error uid={uid}: {e}\n{traceback.format_exc()}")
            self.send_msg(uid, "⚠️ Ошибка. Попробуйте снова.")

    def run(self):
        print("=" * 50)
        print("🚕 Бот таксопарка запущен!")
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        sys.stdout.flush()
        while True:
            try:
                for event in self.longpoll.listen():
                    try:
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            msg = event.object.message
                            peer_id = msg.get('peer_id', 0)
                            uid = msg['from_id']
                            text = msg['text'].strip()
                            action = msg.get('action', {})
                            action_type = action.get('type', '')
                            if peer_id > 2000000000:
                                if action_type in ['chat_invite_user', 'chat_invite_user_by_link']:
                                    member_id = action.get('member_id', uid)
                                    if member_id > 0: self.handle_chat_join(peer_id, member_id)
                                elif action_type == 'chat_kick_user':
                                    member_id = action.get('member_id', uid)
                                    if member_id > 0: self.handle_chat_leave(peer_id, member_id)
                                elif text: self.handle_chat_message(peer_id, uid, text)
                            else:
                                if text: self.handle_ls(uid, text)
                    except Exception as e: log_error(f"Event error: {e}"); continue
            except Exception as e:
                log_error(f"LongPoll error: {e}")
                print(f"⚠️ Ошибка соединения...")
                sys.stdout.flush()
                time.sleep(5)

if __name__ == '__main__':
    try:
        TaxiBot().run()
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()
