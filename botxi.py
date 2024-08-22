import ccxt
import ccxt.async_support as ccxt_async
import time
import logging
import pandas as pd
import joblib
import asyncio
import csv
import os
from datetime import datetime
import json
import tkinter as tk
from tkinter import simpledialog, messagebox
from tkinter import ttk
from tkinter import Tk, Button, Label
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from collections import deque
from cryptography.fernet import Fernet, InvalidToken
from functools import lru_cache
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GridSearchCV


# Configuración del logging para incluir WARNING y ERROR
logging.basicConfig(
    level=logging.ERROR,  # Registra WARNING y ERROR
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),  # Guarda logs en un archivo
        logging.StreamHandler()  # Muestra logs en la consola
    ]
)

# Clave de cifrado (debe generarse una sola vez y almacenarse de manera segura)
encryption_key = Fernet.generate_key()
cipher_suite = Fernet(encryption_key)

# Archivo cifrado donde se guardará la configuración
encrypted_config_file = 'config.enc'

# Variables globales
exchanges_config = {}
symbols_config = []
csv_filename_template = 'trades.csv'
commission_rate = 0.001

rate_limiter = asyncio.Semaphore(10)  # Permite hasta 10 solicitudes concurrentesrate_limiter = asyncio.Semaphore(10)  # Permite hasta 10 solicitudes concurrentes

# Variables necesarias
exchanges = {}
connection_status = {}
actions_log = deque(maxlen=1000)
daily_trades = {}
market_prices = {}
predicted_prices = {}
open_orders = {}
pending_sells = {}
daily_losses = {}
profit_loss = {}
active_symbols = {}
reactivation_thresholds = {}
exchange_running_status = {}
key_file = 'encryption_key.key'

# Ruta del archivo donde se guardará la clave de cifrado
key_file = 'encryption_key.key'

@lru_cache(maxsize=128)
def count_pending_sell_orders(exchange_id, symbol):
    return len(pending_sells[exchange_id][symbol])

def deactivate_token_if_needed(exchange_id, symbol):
    pending_sells_count = count_pending_sell_orders(exchange_id, symbol)
    if pending_sells_count >= 4:  # Desactivar si hay 2 o más órdenes de venta pendientes
        active_symbols[exchange_id][symbol] = False
        logging.info(f"Trading detenido para {symbol} en {exchange_id} debido a {pending_sells_count} órdenes de venta pendientes.")

def reactivate_token_if_needed(exchange_id, symbol):
    if count_pending_sell_orders(exchange_id, symbol) < 4:
        active_symbols[exchange_id][symbol] = True
        logging.info(f"Trading reactivado para {symbol} en {exchange_id}.")

def get_active_symbols_and_exchanges():
    active_symbols_exchanges = {}
    for exchange_id, exchange_data in exchanges_config.items():
        if exchange_data.get('active', False):
            active_symbols_list = [symbol for symbol in exchange_data.get('symbols', []) if active_symbols[exchange_id].get(symbol, True)]
            if active_symbols_list:
                active_symbols_exchanges[exchange_id] = active_symbols_list
    return active_symbols_exchanges

def load_encryption_key():
    # Cargar la clave de cifrado desde el archivo
    if os.path.exists(key_file):
        with open(key_file, 'rb') as key_file_obj:
            return key_file_obj.read()
    else:
        # Si el archivo no existe, generar una nueva clave y guardarla
        new_key = Fernet.generate_key()
        with open(key_file, 'wb') as key_file_obj:
            key_file_obj.write(new_key)
        return new_key

# Cargar la clave de cifrado al iniciar el programa
encryption_key = load_encryption_key()
cipher_suite = Fernet(encryption_key)

# Archivo cifrado donde se guardará la configuración
encrypted_config_file = 'config.enc'

# Cargar configuración cifrada
def load_encrypted_config():
    global exchanges_config, symbols_config, csv_filename_template, commission_rate
    try:
        if not os.path.exists(encrypted_config_file):
            raise FileNotFoundError("El archivo de configuración cifrado no fue encontrado.")

        with open(encrypted_config_file, 'rb') as enc_file:
            encrypted_data = enc_file.read()

        # Intentar descifrar los datos
        decrypted_data = cipher_suite.decrypt(encrypted_data)
        config = json.loads(decrypted_data.decode())

        exchanges_config = config.get('exchanges', {})
        symbols_config = config.get('symbols', [])
        csv_filename_template = config.get('csv_filename', 'trades.csv')
        commission_rate = config.get('commission_rate', 0.001)

        # Asegurarse de que cada exchange tenga una lista de símbolos
        for exchange_id in exchanges_config:
            if 'symbols' not in exchanges_config[exchange_id]:
                exchanges_config[exchange_id]['symbols'] = []

        # Inicialización de estructuras
        initialize_structures()

    except FileNotFoundError as fnf_error:
        logging.error(f"Archivo no encontrado: {fnf_error}")
        save_encrypted_config()  # Crear un archivo de configuración inicial vacío
    except (InvalidToken, ValueError) as decrypt_error:
        logging.error(f"Error al descifrar la configuración cifrada: {decrypt_error}")
        raise decrypt_error
    except Exception as e:
        logging.error(f"Error inesperado al cargar la configuración cifrada: {e}")
        raise e

# Guardar configuración cifrada
def save_encrypted_config():
    config = {
        'exchanges': exchanges_config,
        'symbols': symbols_config,
        'csv_filename': csv_filename_template,
        'commission_rate': commission_rate
    }
    try:
        data = json.dumps(config).encode()
        encrypted_data = cipher_suite.encrypt(data)
        with open(encrypted_config_file, 'wb') as enc_file:
            enc_file.write(encrypted_data)
        logging.info("Configuración guardada exitosamente en archivo cifrado.")
    except Exception as e:
        logging.error(f"Error al guardar la configuración cifrada: {e}")

# Inicializar estructuras globales después de cargar la configuración
def initialize_structures():
    global connection_status, actions_log, daily_trades, market_prices, predicted_prices, open_orders, pending_sells, daily_losses, profit_loss, active_symbols, reactivation_thresholds, exchange_running_status
    connection_status = {exchange_id: 'Disconnected' for exchange_id in exchanges_config.keys()}
    for exchange_id, exchange_data in exchanges_config.items():
        exchange_symbols = exchange_data.get('symbols', [])
        daily_trades[exchange_id] = {symbol: deque(maxlen=1000) for symbol in exchange_symbols}
        market_prices[exchange_id] = {symbol: 0 for symbol in exchange_symbols}
        predicted_prices[exchange_id] = {symbol: 0 for symbol in exchange_symbols}
        open_orders[exchange_id] = {symbol: deque(maxlen=100) for symbol in exchange_symbols}
        pending_sells[exchange_id] = {symbol: deque(maxlen=100) for symbol in exchange_symbols}
        daily_losses[exchange_id] = {symbol: 0 for symbol in exchange_symbols}
        profit_loss[exchange_id] = {symbol: 0 for symbol in exchange_symbols}
        active_symbols = {exchange_id: {symbol: True for symbol in exchange_data.get('symbols', [])} for
                          exchange_id, exchange_data in exchanges_config.items()}
        reactivation_thresholds[exchange_id] = {symbol: None for symbol in exchange_symbols}
    exchange_running_status = {exchange_id: False for exchange_id in exchanges_config.keys()}

class BotGUI:
    def __init__(self, master):
        self.master = master
        master.title("BOTXI Control Panel")
        master.geometry("1400x900")

        style = ttk.Style("darkly")

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        self.create_actions_tab()
        self.create_orders_tab()
        self.create_config_tab()
        self.create_connection_status_panel()

        self.footer_frame = ttk.Frame(master)
        self.footer_frame.pack(fill="x", padx=10, pady=10)

        self.footer_text = tk.Text(self.footer_frame, height=5, wrap="word", state="disabled")
        self.footer_text.pack(fill="both", expand=True)

        self.command_frame = ttk.Frame(master)
        self.command_frame.pack(fill="x", padx=10, pady=10)

        self.command_entry = ttk.Entry(self.command_frame, width=50)
        self.command_entry.pack(side="left", padx=(0, 10))

        self.submit_button = ttk.Button(self.command_frame, text="Enviar Comando", command=self.submit_command)
        self.submit_button.pack(side="left")

        self.start_button = ttk.Button(self.command_frame, text="Iniciar Bot", command=self.start_bot, bootstyle="success")
        self.start_button.pack(side="right", padx=(0, 10))

        self.stop_button = ttk.Button(self.command_frame, text="Detener Bot", command=self.stop_bot, bootstyle="danger")
        self.stop_button.pack(side="right")

        self.account_buttons_frame = ttk.Frame(master)
        self.account_buttons_frame.pack(fill="x", padx=10, pady=10)
        self.account_buttons = {}

        self.update_account_buttons()  # Inicializa los botones en la interfaz

        self.is_running = False
        self.running_accounts = set()

        self.update_interval = 1000  # Actualizar cada 1 segundo
        self.master.after(self.update_interval, self.periodic_update)

        # Inicialización de last_update
        self.last_update = {
            'actions': None,
            'orders': None,
        }

        self.page_size = 20
        self.current_page = 0

        self.update_intervals = {
            'market_prices': 5000,  # 5 segundos
            'orders': 10000,        # 10 segundos
            'balance': 30000,       # 30 segundos
            'profit_loss': 60000    # 1 minuto
        }
        self.start_update_cycles()

    def update_account_buttons(self):
        for widget in self.account_buttons_frame.winfo_children():
            widget.destroy()

        for exchange_id in exchanges_config.keys():
            button_frame = ttk.Frame(self.account_buttons_frame)
            button_frame.pack(side="left", padx=5)

            start_button = ttk.Button(button_frame, text=f"Iniciar {exchange_id}",
                                      command=lambda eid=exchange_id: self.start_account(eid),
                                      bootstyle="success-outline")
            start_button.pack(side="top", pady=2)

            stop_button = ttk.Button(button_frame, text=f"Detener {exchange_id}",
                                     command=lambda eid=exchange_id: self.stop_account(eid),
                                     bootstyle="danger-outline")
            stop_button.pack(side="top", pady=2)

            self.account_buttons[exchange_id] = {"start": start_button, "stop": stop_button}

    def create_config_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Configuración")

        self.exchange_listbox = tk.Listbox(tab)
        self.exchange_listbox.pack(side="left", fill="y", expand=False)

        self.token_listbox = tk.Listbox(tab)
        self.token_listbox.pack(side="left", fill="y", expand=False)

        button_frame = ttk.Frame(tab)
        button_frame.pack(side="left", fill="both", expand=True)

        add_exchange_button = ttk.Button(button_frame, text="Agregar Exchange", command=self.add_exchange)
        add_exchange_button.pack(fill="x", pady=5)

        edit_exchange_button = ttk.Button(button_frame, text="Editar Exchange", command=self.edit_exchange)
        edit_exchange_button.pack(fill="x", pady=5)

        remove_exchange_button = ttk.Button(button_frame, text="Eliminar Exchange", command=self.remove_exchange)
        remove_exchange_button.pack(fill="x", pady=5)

        add_token_button = ttk.Button(button_frame, text="Agregar Token", command=self.add_token)
        add_token_button.pack(fill="x", pady=5)

        edit_token_button = ttk.Button(button_frame, text="Editar Token", command=self.edit_token)
        edit_token_button.pack(fill="x", pady=5)

        remove_token_button = ttk.Button(button_frame, text="Eliminar Token", command=self.remove_token)
        remove_token_button.pack(fill="x", pady=5)

        save_button = ttk.Button(button_frame, text="Guardar Configuración", command=save_encrypted_config)
        save_button.pack(fill="x", pady=5)

        self.load_config_to_listboxes()

    def load_config_to_listboxes(self):
        self.exchange_listbox.delete(0, tk.END)
        self.token_listbox.delete(0, tk.END)

        for exchange_id in exchanges_config:
            self.exchange_listbox.insert(tk.END, exchange_id)

        for symbol in symbols_config:
            self.token_listbox.insert(tk.END, symbol['symbol'])

    def add_exchange(self):
        self.edit_exchange(new=True)

    def edit_exchange(self, new=False):
        if new:
            exchange_id = simpledialog.askstring("Nuevo Exchange", "ID del Exchange:")
            if not exchange_id:
                return
            exchange_data = {
                "name": "",
                "api_key": "",
                "secret": "",
                "password": "",
                "active": True,
                "symbols": []
            }
        else:
            exchange_id = self.exchange_listbox.get(tk.ACTIVE)
            if not exchange_id:
                return
            exchange_data = exchanges_config.get(exchange_id)

        if exchange_data is None:
            messagebox.showerror("Error", "Exchange no encontrado")
            return

        # Crear un cuadro de diálogo para todas las configuraciones
        dialog = tk.Toplevel(self.master)
        dialog.title("Configuración de Exchange")

        tk.Label(dialog, text="Nombre del Exchange").grid(row=0, column=0)
        tk.Label(dialog, text="API Key").grid(row=1, column=0)
        tk.Label(dialog, text="Secret Key").grid(row=2, column=0)
        tk.Label(dialog, text="Password").grid(row=3, column=0)
        tk.Label(dialog, text="Activo").grid(row=4, column=0)
        tk.Label(dialog, text="Tokens").grid(row=5, column=0)  # Nueva línea para los tokens

        name_var = tk.StringVar(value=exchange_data['name'])
        api_key_var = tk.StringVar(value=exchange_data['api_key'])
        secret_var = tk.StringVar(value=exchange_data['secret'])
        password_var = tk.StringVar(value=exchange_data['password'])
        active_var = tk.BooleanVar(value=exchange_data['active'])

        tk.Entry(dialog, textvariable=name_var).grid(row=0, column=1)
        tk.Entry(dialog, textvariable=api_key_var).grid(row=1, column=1)
        tk.Entry(dialog, textvariable=secret_var).grid(row=2, column=1)
        tk.Entry(dialog, textvariable=password_var).grid(row=3, column=1)
        tk.Checkbutton(dialog, variable=active_var).grid(row=4, column=1)

        # Selector de tokens
        token_listbox = tk.Listbox(dialog, selectmode="multiple")
        token_listbox.grid(row=5, column=1)

        # Agregar todos los tokens disponibles a la lista
        for token in symbols_config:
            token_listbox.insert(tk.END, token['symbol'])

        # Seleccionar los tokens ya configurados
        for i, token in enumerate(symbols_config):
            if token['symbol'] in exchange_data['symbols']:
                token_listbox.selection_set(i)

        def save_changes():
            exchange_data.update({
                "name": name_var.get(),
                "api_key": api_key_var.get(),
                "secret": secret_var.get(),
                "password": password_var.get(),
                "active": active_var.get(),
                "symbols": [token_listbox.get(i) for i in token_listbox.curselection()]
                # Guardar los tokens seleccionados
            })
            exchanges_config[exchange_id] = exchange_data
            self.load_config_to_listboxes()
            self.update_account_buttons()
            dialog.destroy()

        tk.Button(dialog, text="Guardar", command=save_changes).grid(row=6, column=0, columnspan=2)

    def remove_exchange(self):
        selected_exchange = self.exchange_listbox.get(tk.ACTIVE)
        if selected_exchange:
            del exchanges_config[selected_exchange]
            self.load_config_to_listboxes()
            self.update_account_buttons()

    def add_token(self):
        self.edit_token(new=True)

    def edit_token(self, new=False):
        if new:
            symbol = simpledialog.askstring("Nuevo Token", "Símbolo del Token (e.g., BTC/USDT):")
            if not symbol:
                return
            token_data = {
                "symbol": symbol,
                "spread": 0.0,
                "take_profit": 0.0,
                "trade_amount": 0.0,
                "max_orders": 1,
                "order_timeout": 60,
                "trailing_stop_distance": 0.0,
                "max_daily_loss": 0.0,
                "exchanges": []  # Nueva lista para almacenar los exchanges asignados
            }
        else:
            symbol = self.token_listbox.get(tk.ACTIVE)
            if not symbol:
                return
            token_data = next((s for s in symbols_config if s['symbol'] == symbol), None)

        if token_data is None:
            messagebox.showerror("Error", "Token no encontrado")
            return

        # Crear un cuadro de diálogo para todas las configuraciones
        dialog = tk.Toplevel(self.master)
        dialog.title("Configuración de Token")

        tk.Label(dialog, text="Spread").grid(row=0, column=0)
        tk.Label(dialog, text="Take Profit").grid(row=1, column=0)
        tk.Label(dialog, text="Cantidad de Trade").grid(row=2, column=0)
        tk.Label(dialog, text="Número máximo de órdenes").grid(row=3, column=0)
        tk.Label(dialog, text="Tiempo de expiración de órdenes").grid(row=4, column=0)
        tk.Label(dialog, text="Trailing Stop Distance").grid(row=5, column=0)
        tk.Label(dialog, text="Máxima pérdida diaria").grid(row=6, column=0)
        tk.Label(dialog, text="Exchanges").grid(row=7, column=0)

        spread_var = tk.DoubleVar(value=token_data['spread'])
        take_profit_var = tk.DoubleVar(value=token_data['take_profit'])
        trade_amount_var = tk.DoubleVar(value=token_data['trade_amount'])
        max_orders_var = tk.IntVar(value=token_data['max_orders'])
        order_timeout_var = tk.IntVar(value=token_data['order_timeout'])
        trailing_stop_distance_var = tk.DoubleVar(value=token_data['trailing_stop_distance'])
        max_daily_loss_var = tk.DoubleVar(value=token_data['max_daily_loss'])

        tk.Entry(dialog, textvariable=spread_var).grid(row=0, column=1)
        tk.Entry(dialog, textvariable=take_profit_var).grid(row=1, column=1)
        tk.Entry(dialog, textvariable=trade_amount_var).grid(row=2, column=1)
        tk.Entry(dialog, textvariable=max_orders_var).grid(row=3, column=1)
        tk.Entry(dialog, textvariable=order_timeout_var).grid(row=4, column=1)
        tk.Entry(dialog, textvariable=trailing_stop_distance_var).grid(row=5, column=1)
        tk.Entry(dialog, textvariable=max_daily_loss_var).grid(row=6, column=1)

        # Crear checkboxes para los exchanges
        exchange_vars = {}
        for i, exchange_id in enumerate(exchanges_config.keys()):
            var = tk.BooleanVar(value=exchange_id in token_data.get('exchanges', []))
            exchange_vars[exchange_id] = var
            tk.Checkbutton(dialog, text=exchange_id, variable=var).grid(row=7 + i, column=1, sticky='w')

        def save_changes():
            token_data.update({
                "spread": spread_var.get(),
                "take_profit": take_profit_var.get(),
                "trade_amount": trade_amount_var.get(),
                "max_orders": max_orders_var.get(),
                "order_timeout": order_timeout_var.get(),
                "trailing_stop_distance": trailing_stop_distance_var.get(),
                "max_daily_loss": max_daily_loss_var.get(),
                "exchanges": [exchange_id for exchange_id, var in exchange_vars.items() if var.get()]
            })

            if new:
                symbols_config.append(token_data)
            else:
                for i, t in enumerate(symbols_config):
                    if t['symbol'] == symbol:
                        symbols_config[i] = token_data
                        break

            # Actualizar la configuración de los exchanges
            for exchange_id in exchanges_config.keys():
                if exchange_id in token_data['exchanges']:
                    if token_data['symbol'] not in exchanges_config[exchange_id]['symbols']:
                        exchanges_config[exchange_id]['symbols'].append(token_data['symbol'])
                else:
                    if token_data['symbol'] in exchanges_config[exchange_id]['symbols']:
                        exchanges_config[exchange_id]['symbols'].remove(token_data['symbol'])

            self.load_config_to_listboxes()
            dialog.destroy()

        tk.Button(dialog, text="Guardar", command=save_changes).grid(row=8 + len(exchanges_config), column=0,
                                                                     columnspan=2)

    def remove_token(self):
        selected_token = self.token_listbox.get(tk.ACTIVE)
        if selected_token:
            symbols_config[:] = [d for d in symbols_config if d.get('symbol') != selected_token]
            self.load_config_to_listboxes()

    def create_actions_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Acciones Recientes")

        columns = ("Fecha/Hora", "Exchange", "Acción", "Símbolo", "Cantidad", "Precio", "Profit/Loss")
        self.actions_tree = ttk.Treeview(tab, columns=columns, show="headings")
        for col in columns:
            self.actions_tree.heading(col, text=col)
        self.actions_tree.pack(expand=True, fill="both")

        self.prev_button = ttk.Button(tab, text="Anterior", command=self.prev_page)
        self.prev_button.pack(side="left")
        self.next_button = ttk.Button(tab, text="Siguiente", command=self.next_page)
        self.next_button.pack(side="right")

    def create_orders_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Órdenes Activas")

        columns = ("Exchange", "Símbolo", "ID Orden", "Tipo", "Cantidad", "Precio", "Estado", "Tiempo Activo")
        self.orders_tree = ttk.Treeview(tab, columns=columns, show="headings")
        for col in columns:
            self.orders_tree.heading(col, text=col)
        self.orders_tree.pack(expand=True, fill="both")

    def create_connection_status_panel(self):
        status_frame = ttk.LabelFrame(self.master, text="Estado de Exchanges")
        status_frame.pack(fill="x", padx=10, pady=10)

        self.status_labels = {}
        for exchange_id in exchanges_config.keys():
            label = ttk.Label(status_frame, text=f"{exchange_id}: Desconectado | No iniciado")
            label.pack(anchor="w", padx=5, pady=2)
            self.status_labels[exchange_id] = label

    def update_footer(self, actions):
        self.footer_text.config(state="normal")
        self.footer_text.delete("1.0", tk.END)
        if actions:
            last_actions = list(actions)[-5:]
            self.footer_text.insert(tk.END, "\n".join(last_actions))
        self.footer_text.config(state="disabled")

    def run_bot(self):
        for exchange_id in self.running_accounts:
            asyncio.create_task(self.run_account(exchange_id))
        logging.info("Bot iniciado")

    def start_bot(self):
        if not self.is_running:
            self.is_running = True
            self.running_accounts = set(exchanges_config.keys())
            for exchange_id in self.running_accounts:
                exchange_running_status[exchange_id] = True
            asyncio.create_task(self.run_bot())
            self.update_connection_status()
            logging.info("Bot iniciado")

    async def run_bot(self):
        try:
            tasks = []
            for exchange_id in self.running_accounts:
                tasks.append(asyncio.create_task(self.run_account(exchange_id)))
            await asyncio.gather(*tasks)
        except Exception as e:
            logging.error(f"Error al ejecutar el bot: {e}")
        finally:
            await shutdown_bot()


    async def run_gui(self):
        while True:
            self.update_gui()
            self.master.update()
            await asyncio.sleep(0.1)  # Actualiza cada 100ms

    def stop_account(self, exchange_id):
        if exchange_id in self.running_accounts:
            self.running_accounts.remove(exchange_id)
            exchange_running_status[exchange_id] = False
            asyncio.create_task(self.shutdown_account(exchange_id))
            self.update_connection_status()
            logging.info(f"Deteniendo operaciones para {exchange_id}")

    async def async_shutdown_procedures(self):
        await shutdown_bot()
        for exchange_id, exchange in exchanges.items():
            if exchange:
                await exchange.close()
        logging.info("Bot detenido completamente")

    async def stop_bot(self):
        if self.is_running:
            self.is_running = False
            self.running_accounts.clear()
            for exchange_id in exchanges_config.keys():
                exchange_running_status[exchange_id] = False
            self.update_connection_status()
            await shutdown_bot()
            for exchange_id, exchange in exchanges.items():
                await exchange.close()
            logging.info("Bot detenido completamente")

    def start_account(self, exchange_id):
        if exchange_id not in self.running_accounts:
            self.running_accounts.add(exchange_id)
            exchange_running_status[exchange_id] = True
            logging.info(f"Iniciando tarea para {exchange_id}")
            asyncio.create_task(self.run_account(exchange_id))
            self.update_connection_status()
            logging.info(f"Tarea iniciada para {exchange_id}")

    def stop_account(self, exchange_id):
        if exchange_id in self.running_accounts:
            self.running_accounts.remove(exchange_id)
            exchange_running_status[exchange_id] = False
            asyncio.create_task(self.shutdown_account(exchange_id))
            self.update_connection_status()
            logging.info(f"Deteniendo operaciones para {exchange_id}")

    def update_connection_status(self):
        for exchange_id, status in connection_status.items():
            if exchange_id in self.status_labels:
                label = self.status_labels[exchange_id]
                conn_status = "Conectado" if status == 'Connected' else "Desconectado"
                run_status = "Iniciado" if exchange_running_status[exchange_id] else "No iniciado"

                if status == 'Connected' and exchange_running_status[exchange_id]:
                    color = "lime"
                elif status == 'Connected':
                    color = "yellow"
                else:
                    color = "red"

                label.config(text=f"{exchange_id}: {conn_status} | {run_status}", foreground=color)
            else:
                logging.error(f"Exchange ID '{exchange_id}' no se encontró en status_labels.")

    async def shutdown_account(self, exchange_id):
        await close_account_open_orders(exchange_id)
        await cancel_account_pending_buys(exchange_id)
        exchange_running_status[exchange_id] = False
        self.update_connection_status()
        await exchanges[exchange_id].close()  # Añade esta línea
        logging.info(f"Operaciones detenidas y órdenes cerradas para {exchange_id}")

    def submit_command(self):
        command = self.command_entry.get()
        self.command_entry.delete(0, tk.END)
        if command.lower() == 'stop':
            asyncio.create_task(self.stop_bot())
        else:
            handle_command(command)

    async def run_account(self, exchange_id):
        try:
            await initialize_exchange(exchange_id)
            asyncio.create_task(reconnect_exchange(exchange_id))

            tasks = []
            exchange = exchanges.get(exchange_id)
            if exchange and exchange_id in self.running_accounts:
                exchange_symbols = exchanges_config[exchange_id].get('symbols', [])
                logging.info(f"Símbolos configurados para {exchange_id}: {exchange_symbols}")

                for symbol_config in symbols_config:
                    if symbol_config['symbol'] in exchange_symbols:
                        logging.info(f"Creando tarea para {symbol_config['symbol']} en {exchange_id}")
                        task = asyncio.create_task(self.process_symbol(symbol_config, exchange_id))
                        tasks.append(task)
                    else:
                        logging.info(f"Símbolo {symbol_config['symbol']} no configurado para {exchange_id}")

            logging.info(f"Total de tareas creadas para {exchange_id}: {len(tasks)}")

            if tasks:
                await asyncio.gather(*tasks)
            else:
                logging.warning(f"No se crearon tareas para {exchange_id}. Verifica la configuración.")

        except asyncio.CancelledError:
            logging.info(f"Tarea para {exchange_id} cancelada")
        except Exception as e:
            logging.error(f"Error en la ejecución de {exchange_id}: {e}")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logging.info(f"Tareas para {exchange_id} finalizadas")

    def periodic_update(self):
        self.update_gui()
        self.master.after(self.update_interval, self.periodic_update)

    def update_gui(self):
        self.update_actions_tab()
        self.update_orders_tab()
        self.update_connection_status()
        self.update_footer(actions_log)
        self.master.update_idletasks()

    def update_actions_tab(self):
        current_data = self.get_actions_data()
        if current_data != self.last_update['actions']:
            self.actions_tree.delete(*self.actions_tree.get_children())
            start = self.current_page * self.page_size
            end = start + self.page_size
            for item in current_data[start:end]:
                self.actions_tree.insert("", "end", values=item)
            self.last_update['actions'] = current_data

    def update_orders_tab(self):
        self.orders_tree.delete(*self.orders_tree.get_children())
        current_time = time.time()
        for exchange_id, symbols in open_orders.items():
            for symbol, orders in symbols.items():
                for order in orders:
                    timestamp = order.get('timestamp')
                    time_active = current_time - (timestamp / 1000 if timestamp else current_time)
                    amount = order.get('amount')
                    price = order.get('price')
                    self.orders_tree.insert("", "end", values=(
                        exchange_id,
                        order.get('symbol', ''),
                        order.get('id', ''),
                        order.get('side', ''),
                        f"{amount:.8f}" if amount is not None else "N/A",
                        f"{price:.8f}" if price is not None else "N/A",
                        order.get('status', ''),
                        f"{time_active:.2f} segundos" if timestamp else "N/A"
                    ))

    def get_actions_data(self):
        data = []
        for exchange_id, symbols in daily_trades.items():
            for symbol, trades in symbols.items():
                for trade in list(trades)[-10:]:
                    profit_loss = calculate_trade_profit_loss(trade)
                    data.append((
                        trade['timestamp'], exchange_id, trade['side'], trade['symbol'],
                        f"{trade['amount']:.8f}", f"{trade['price']:.8f}", f"{profit_loss:.8f}"
                    ))
        return data

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_actions_tab()

    def next_page(self):
        if (self.current_page + 1) * self.page_size < len(self.get_actions_data()):
            self.current_page += 1
            self.update_actions_tab()

    def start_update_cycles(self):
        # Solo llama a los ciclos de actualización que son relevantes para las pestañas actuales
        valid_update_types = ['orders', 'actions']
        for update_type, interval in self.update_intervals.items():
            if update_type in valid_update_types:
                self.master.after(interval, lambda t=update_type: self.update_cycle(t))

    def update_cycle(self, update_type):
        getattr(self, f"update_{update_type}_tab")()
        self.master.after(self.update_intervals[update_type], lambda: self.update_cycle(update_type))

    async def process_symbol(self, symbol_config, exchange_id):
        exchange = exchanges[exchange_id]
        symbol = symbol_config['symbol']
        logging.info(f"Iniciando procesamiento de {symbol} en {exchange_id}")
        spread = symbol_config['spread']
        take_profit = symbol_config['take_profit']
        trade_amount = symbol_config['trade_amount']
        max_orders = symbol_config['max_orders']
        order_timeout = symbol_config['order_timeout']
        trailing_stop_distance = symbol_config['trailing_stop_distance']
        max_daily_loss = symbol_config['max_daily_loss']

        exchange_symbols = exchanges_config[exchange_id].get('symbols', [])
        if symbol not in exchange_symbols:
            logging.info(f"Símbolo {symbol} no configurado para {exchange_id}, saltando")
            return

        try:
            data = await fetch_ohlcv_async(symbol, exchange_id, timeframe='1h', limit=1000)
            model = train_model(data, symbol, exchange_id)
        except Exception as e:
            logging.error(f"Error al entrenar el modelo para {symbol} en {exchange_id}: {e}")
            return

        while exchange_id in self.running_accounts and exchange_running_status[exchange_id]:
            try:
                if not exchange_running_status[exchange_id]:
                    logging.info(f"Deteniendo procesamiento para {symbol} en {exchange_id}")
                    break

                # Verificar si debe desactivar el trading
                deactivate_token_if_needed(exchange_id, symbol)

                if not active_symbols[exchange_id][symbol]:
                    logging.info(f"Símbolo {symbol} no activo en {exchange_id}, esperando reactivación")
                    await asyncio.sleep(10)
                    # Verificar si puede reactivar el trading
                    reactivate_token_if_needed(exchange_id, symbol)
                    continue

                prices = await get_market_prices_async(exchange_id)
                market_price = prices.get(symbol)
                if market_price is None:
                    logging.warning(f"No se pudo obtener el precio para {symbol} en {exchange_id}")
                    await asyncio.sleep(10)
                    continue

                logging.info(f"Precio de mercado para {symbol} en {exchange_id}: {market_price}")

                ohlcv = await fetch_ohlcv_async(symbol, exchange_id, timeframe='1h', limit=1)
                if not ohlcv.empty:
                    row = ohlcv.iloc[-1]
                    open, high, low, close, volume = row['open'], row['high'], row['low'], row['close'], row['volume']
                else:
                    logging.warning(f"No OHLCV data available for {symbol} on {exchange_id}")
                    await asyncio.sleep(10)
                    continue

                predicted_price = predict_next_price(model, symbol, exchange_id, open, high, low, close, volume)
                logging.info(f"Precio predicho para {symbol} en {exchange_id}: {predicted_price}")

                if predicted_price > market_price and exchange_running_status[exchange_id]:
                    logging.info(f"Intentando abrir órdenes de compra para {symbol} en {exchange_id}")
                    for i in range(max_orders - len(open_orders[exchange_id][symbol])):
                        if not exchange_running_status[exchange_id]:
                            break
                        buy_price = market_price * (1 - spread * (i + 1))
                        order = await place_order_async(symbol, 'buy', trade_amount, buy_price, exchange_id)
                        if order:
                            logging.info(f"Orden de compra abierta en {exchange_id} para {symbol}: {order}")
                        else:
                            logging.info(f"No se pudo abrir orden de compra en {exchange_id} para {symbol}")
                        await asyncio.sleep(1)

                # Manejo de órdenes de compra abiertas
                if exchange_running_status[exchange_id]:
                    await manage_open_buy_orders(exchange_id, symbol, order_timeout)

                # Colocación de órdenes de venta
                if exchange_running_status[exchange_id]:
                    await place_sell_orders(exchange_id, symbol, take_profit)

                # Colocación de trailing stop
                if exchange_running_status[exchange_id]:
                    await manage_trailing_stop(exchange_id, symbol, trailing_stop_distance)

                # Control de pérdidas diarias
                daily_loss = calculate_daily_loss(symbol, exchange_id)
                if daily_loss > max_daily_loss:
                    logging.info(
                        f"Pérdida diaria máxima alcanzada para {symbol} en {exchange_id}, deteniendo operaciones")
                    active_symbols[exchange_id][symbol] = False
                    reactivation_thresholds[exchange_id][symbol] = market_price * 1.05
                    await asyncio.sleep(10)
                    continue

                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error en el procesamiento de {symbol} en {exchange_id}: {e}")
                await asyncio.sleep(10)

        logging.info(f"Procesamiento detenido para {symbol} en {exchange_id}")

# Colocación de órdenes de compra
async def place_order_async(symbol, side, amount, price, exchange_id, retries=3):
    if not exchange_running_status[exchange_id]:
        logging.info(f"No se colocará la orden {side} para {symbol} en {exchange_id} porque el exchange está detenido")
        return None

    for attempt in range(retries):
        try:
            exchange = exchanges[exchange_id]
            order = await exchange.create_order(symbol, 'limit', side, amount, price)
            logging.info(f"Orden {side} colocada en {exchange_id}: {order}")
            trade_record = {
                'timestamp': datetime.now().isoformat(),
                'exchange': exchange_id,
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'price': price,
                'order_id': order['id']
            }
            daily_trades[exchange_id][symbol].append(trade_record)
            open_orders[exchange_id][symbol].append(order)
            save_trade_to_csv(trade_record, exchange_id)
            return order
        except Exception as e:
            logging.error(f"Error al colocar la orden {side} para {symbol} en {exchange_id}: {e}")
            if not exchange_running_status[exchange_id]:
                logging.info(f"El exchange {exchange_id} ha sido detenido durante el intento de colocar la orden")
                return None
            await asyncio.sleep(2 ** attempt)
    logging.error(
        f"No se pudo colocar la orden {side} para {symbol} en {exchange_id} después de {retries} intentos")
    return None

# Cancelación de órdenes de compra después de 1 minuto
async def manage_open_buy_orders(exchange_id, symbol, order_timeout):
    current_time = time.time()
    for order in list(open_orders[exchange_id][symbol]):
        order_info = await exchanges[exchange_id].fetch_order(order['id'], symbol)
        if order_info['status'] == 'closed':
            # Si la orden está cerrada, la manejamos como antes (se mueve a pending_sells)
            logging.info(f"Orden de compra ejecutada para {symbol} en {exchange_id}: {order_info}")
            daily_trades[exchange_id][symbol].append({
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'side': 'buy',
                'amount': order_info['amount'],
                'price': order_info['price'],
                'order_id': order_info['id']
            })
            pending_sells[exchange_id][symbol].append(order_info)
            open_orders[exchange_id][symbol].remove(order)
        elif order_info['status'] == 'open' and order_info['side'] == 'buy' and current_time - order_info[
            'timestamp'] / 1000 > order_timeout:
            # Solo cancelamos órdenes de compra abiertas que han excedido el timeout
            await cancel_order_async(order['id'], symbol, exchange_id)
            open_orders[exchange_id][symbol].remove(order)


# Colocación de órdenes de venta
async def place_sell_orders(exchange_id, symbol, take_profit):
    for buy_order in list(pending_sells[exchange_id][symbol]):
        sell_price = buy_order['price'] * (1 + take_profit)
        if market_prices[exchange_id][symbol] >= sell_price:
            await place_order_async(symbol, 'sell', buy_order['amount'], sell_price, exchange_id)
            pending_sells[exchange_id][symbol].remove(buy_order)


# Colocación de trailing stop
async def manage_trailing_stop(exchange_id, symbol, trailing_stop_distance):
    for buy_order in list(pending_sells[exchange_id][symbol]):
        trailing_stop_price = buy_order['price'] * (1 + trailing_stop_distance)
        if market_prices[exchange_id][symbol] <= trailing_stop_price:
            await place_order_async(symbol, 'sell', buy_order['amount'], market_prices[exchange_id][symbol], exchange_id)
            logging.info(
                f"Trailing stop activado para orden {buy_order['id']} en {exchange_id}, vendiendo a {market_prices[exchange_id][symbol]}")
            pending_sells[exchange_id][symbol].remove(buy_order)

async def cancel_pending_buy_orders(exchange_id, symbol, order_timeout):
    """
    Cancela las órdenes de compra que han estado pendientes por más de `order_timeout` segundos.
    """
    current_time = time.time()
    for order in list(open_orders[exchange_id][symbol]):
        if order['side'] == 'buy':  # Verifica que la orden sea de compra
            order_info = await exchanges[exchange_id].fetch_order(order['id'], symbol)
            order_age = current_time - (order_info['timestamp'] / 1000)  # Convierte de ms a s
            if order_info['status'] == 'open' and order_age > order_timeout:
                await cancel_order_async(order['id'], symbol, exchange_id)
                open_orders[exchange_id][symbol].remove(order)
                logging.info(f"Orden de compra {order['id']} cancelada en {exchange_id} para {symbol} después de {order_timeout} segundos")

async def close_account_open_orders(exchange_id):
    tasks = []
    for symbol, orders in open_orders[exchange_id].items():
        for order in list(orders):
            if order['side'] == 'buy':
                tasks.append(cancel_order_async(order['id'], symbol, exchange_id))
                orders.remove(order)
    await asyncio.gather(*tasks)
    logging.info(f"Todas las órdenes de compra abiertas han sido cerradas para {exchange_id}")

async def cancel_account_pending_buys(exchange_id):
    tasks = []
    for symbol, orders in pending_sells[exchange_id].items():
        for order in list(orders):
            if order['side'] == 'buy':
                tasks.append(cancel_order_async(order['id'], symbol, exchange_id))
                orders.remove(order)
    await asyncio.gather(*tasks)
    logging.info(f"Todas las órdenes de compra pendientes han sido canceladas para {exchange_id}")

# Inicializar exchanges y otras tareas de configuración
async def initialize_exchanges():
    for exchange_id, creds in exchanges_config.items():
        if creds.get('active', False):
            try:
                await initialize_exchange(exchange_id)
                logging.info(f"Exchange {exchange_id} inicializado correctamente")
            except Exception as e:
                logging.error(f"Error al inicializar {exchange_id}: {e}")


async def initialize_exchange(exchange_id):
    creds = exchanges_config[exchange_id]
    if creds.get('active', False):
        try:
            exchange_class = getattr(ccxt_async, creds['name'])
            exchange_params = {
                'apiKey': creds['api_key'],
                'secret': creds['secret'],
                'enableRateLimit': True
            }
            if 'password' in creds:
                exchange_params['password'] = creds['password']

            exchanges[exchange_id] = exchange_class(exchange_params)
            await exchanges[exchange_id].load_markets()
            connection_status[exchange_id] = 'Connected'
            logging.info(f"Exchange {exchange_id} conectado exitosamente.")

            # Cargar órdenes pendientes
            await load_pending_orders(exchange_id)

        except Exception as e:
            logging.error(f"Error al inicializar el exchange {exchange_id}: {e}")
            connection_status[exchange_id] = 'Disconnected'
        await asyncio.sleep(1)


async def load_pending_orders(exchange_id):
    exchange = exchanges[exchange_id]
    for symbol in exchanges_config[exchange_id]['symbols']:
        try:
            open_orders_list = await exchange.fetch_open_orders(symbol)
            for order in open_orders_list:
                if order['side'] == 'sell':
                    pending_sells[exchange_id][symbol].append(order)
                elif order['side'] == 'buy':
                    open_orders[exchange_id][symbol].append(order)

            pending_sells_count = len(pending_sells[exchange_id][symbol])
            logging.info(f"Cargadas {pending_sells_count} órdenes de venta pendientes para {symbol} en {exchange_id}")

            # Verificar si necesitamos desactivar el trading para este símbolo
            deactivate_token_if_needed(exchange_id, symbol)

        except Exception as e:
            logging.error(f"Error al cargar órdenes pendientes para {symbol} en {exchange_id}: {e}")

async def shutdown_bot():
    logging.info("Cerrando bot y todas las sesiones de cliente...")
    tasks = []
    for exchange_id, exchange in exchanges.items():
        if exchange:
            tasks.append(exchange.close())
    if tasks:
        await asyncio.gather(*tasks)
    logging.info("Todas las sesiones de cliente han sido cerradas.")

async def reconnect_exchanges():
    while True:
        tasks = [reconnect_exchange(exchange_id) for exchange_id in exchanges_config.keys()]
        await asyncio.gather(*tasks)
        await asyncio.sleep(10)

async def reconnect_exchange(exchange_id):
    if connection_status[exchange_id] == 'Disconnected':
        try:
            await initialize_exchange(exchange_id)
        except Exception as e:
            logging.error(f"Error al reconectar el exchange {exchange_id}: {e}")
    await asyncio.sleep(1)

def validate_data(data):
    if data is None or len(data) == 0:
        raise ValueError("Data is empty or None")
    return True

async def fetch_ohlcv_async(symbol, exchange_id, timeframe='1h', limit=1000, retries=5):
    for attempt in range(retries):
        try:
            data = await exchanges[exchange_id].fetch_ohlcv(symbol, timeframe, limit=limit)
            if not data:
                raise ValueError("Received empty data")
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            logging.info(f"OHLCV data fetched for {symbol} on {exchange_id}: {df.tail()}")
            return df
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logging.error(f"Error fetching OHLCV data for {symbol} on {exchange_id}: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

def train_model(data, symbol, exchange_id):
    model_filename = f'price_prediction_model_{exchange_id}_{symbol.replace("/", "_")}.pkl'
    try:
        best_model = joblib.load(model_filename)
        logging.info(f"Modelo cargado desde el archivo existente para {symbol} en {exchange_id}")
    except FileNotFoundError:
        logging.info(f"Archivo de modelo no encontrado para {symbol} en {exchange_id}. Entrenando un nuevo modelo")
        data['target'] = data['close'].shift(-1)
        data.dropna(inplace=True)
        X = data[['open', 'high', 'low', 'close', 'volume']]
        y = data['target']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        param_grid = {
            'n_estimators': [50, 100, 200],
            'max_depth': [None, 10, 20, 30],
            'min_samples_split': [2, 5, 10]
        }
        rf = RandomForestRegressor(random_state=42)
        grid_search = GridSearchCV(estimator=rf, param_grid=param_grid, cv=3, n_jobs=-1, verbose=0)
        grid_search.fit(X_train, y_train)

        best_model = grid_search.best_estimator_
        joblib.dump(best_model, model_filename)
        logging.info(f"Modelo entrenado y guardado en archivo para {symbol} en {exchange_id}")
    return best_model

async def get_market_prices_async(exchange_id, retries=5):
    active_symbols_exchanges = get_active_symbols_and_exchanges()
    symbols = active_symbols_exchanges.get(exchange_id, [])

    if not symbols:
        return {}

    for attempt in range(retries):
        try:
            async with rate_limiter:  # Cambia rate_limiter.wait() por async with rate_limiter:
                tickers = await exchanges[exchange_id].fetch_tickers(symbols)
                for symbol, ticker in tickers.items():
                    market_prices[exchange_id][symbol] = ticker['last']
                return {symbol: market_prices[exchange_id][symbol] for symbol in symbols}
        except Exception as e:
            logging.error(f"Error al obtener precios de mercado para {symbols} en {exchange_id}: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    raise Exception(f"Failed to fetch market prices for {symbols} on {exchange_id} after {retries} attempts")

async def cancel_order_async(order_id, symbol, exchange_id):
    try:
        await exchanges[exchange_id].cancel_order(order_id, symbol)
        logging.info(f"Orden de compra cancelada: {order_id} para {symbol} en {exchange_id}")
    except Exception as e:
        logging.error(f"Error al cancelar la orden {order_id} para {symbol} en {exchange_id}: {e}")

async def close_all_open_buy_orders():
    logging.info("Cerrando todas las órdenes de compra abiertas...")
    tasks = [close_account_open_buy_orders(exchange_id) for exchange_id in exchanges_config.keys()]
    await asyncio.gather(*tasks)
    logging.info("Todas las órdenes de compra abiertas han sido cerradas")

async def close_account_open_buy_orders(exchange_id):
    async with asyncio.Lock():
        tasks = []
        for symbol, orders in open_orders[exchange_id].items():
            for order in list(orders):
                if order['side'] == 'buy':
                    tasks.append(cancel_order_async(order['id'], symbol, exchange_id))
                    orders.remove(order)
        await asyncio.gather(*tasks)
        logging.info(f"Órdenes de compra cerradas para {exchange_id}")

def predict_next_price(model, symbol, exchange_id, open, high, low, close, volume):
    data = pd.DataFrame({
        'open': [open],
        'high': [high],
        'low': [low],
        'close': [close],
        'volume': [volume]
    })
    prediction = model.predict(data)[0]
    logging.info(f"Predicción del próximo precio para {symbol} en {exchange_id}: {prediction}")
    predicted_prices[exchange_id][symbol] = prediction
    return prediction

def calculate_daily_loss(symbol, exchange_id):
    total_loss = 0
    for trade in daily_trades[exchange_id][symbol]:
        if trade['side'] == 'sell':
            matching_buy = next((t for t in daily_trades[exchange_id][symbol] if
                                 t['side'] == 'buy' and t['amount'] == trade['amount'] and t['order_id'] ==
                                 trade['order_id']), None)
            if matching_buy:
                loss = matching_buy['price'] - trade['price']
                total_loss += loss
    daily_losses[exchange_id][symbol] = total_loss
    logging.info(f"Pérdida total del día calculada para {symbol} en {exchange_id}: {total_loss}")
    return total_loss

def calculate_profit_loss():
    for exchange_id, symbols in daily_trades.items():
        for symbol in symbols_config:
            symbol_name = symbol['symbol']
            profit_loss[exchange_id][symbol_name] = 0
            for trade in symbols[symbol_name]:
                if trade['side'] == 'sell':
                    matching_buy = next((t for t in symbols[symbol_name] if
                                         t['side'] == 'buy' and t['amount'] == trade['amount']), None)
                    if matching_buy:
                        profit = (trade['price'] - matching_buy['price']) * trade['amount']
                        profit_loss[exchange_id][symbol_name] += profit

def calculate_trade_profit_loss(trade):
    if trade['side'] == 'sell':
        matching_buy = next((t for t in daily_trades[trade['exchange']][trade['symbol']] if
                             t['side'] == 'buy' and t['amount'] == trade['amount'] and t['order_id'] ==
                             trade['order_id']), None)
        if matching_buy:
            return (trade['price'] - matching_buy['price']) * trade['amount']
    return 0

def calculate_total_invested(exchange_id, symbol):
    return sum(trade['amount'] * trade['price'] for trade in daily_trades[exchange_id][symbol] if
               trade['side'] == 'buy')

def save_trade_to_csv(trade, exchange_id):
    csv_filename = f"{csv_filename_template.split('.')[0]}_{exchange_id}.csv"
    file_exists = os.path.isfile(csv_filename)
    with open(csv_filename, mode='a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=trade.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)

def handle_command(command):
    # Implementa aquí la lógica para manejar los comandos
    logging.info(f"Comando recibido: {command}")
    # Puedes agregar más lógica aquí según los comandos que quieras manejar


async def main():
    try:
        # Cargar la configuración cifrada antes de iniciar la GUI
        load_encrypted_config()
        logging.info(f"Configuración cargada. Exchanges configurados: {list(exchanges_config.keys())}")
        logging.info(f"Símbolos configurados: {[s['symbol'] for s in symbols_config]}")

        logging.info(f"Configuración de exchanges:")
        for exchange_id, exchange_data in exchanges_config.items():
            logging.info(f"{exchange_id}: {exchange_data}")

        # Inicializar la GUI
        root = tk.Tk()
        gui = BotGUI(root)

        # Inicializar exchanges y otras tareas de configuración
        await initialize_exchanges()

        # Crear una tarea para ejecutar el bot
        bot_task = asyncio.create_task(gui.run_bot())

        # Integrar el bucle de eventos de asyncio con tkinter
        gui_task = asyncio.create_task(gui.run_gui())

        # Esperar a que ambas tareas (GUI y bot) se completen
        await asyncio.gather(gui_task, bot_task)

    except KeyboardInterrupt:
        logging.info("Programa terminado por el usuario")
    except Exception as e:
        logging.error(f"Error inesperado: {e}")
        logging.exception("Traceback completo:")
    finally:
        logging.info("Iniciando cierre del programa...")
        await shutdown_bot()  # Cerrar las sesiones de cliente

        # Cancelar todas las tareas pendientes
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

        # Esperar a que todas las tareas se cancelen
        await asyncio.gather(*asyncio.all_tasks(), return_exceptions=True)

        logging.info("Programa terminado completamente")

if __name__ == "__main__":
    asyncio.run(main())

