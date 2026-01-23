import cv2
import socket
import time
import threading
from tkinter import *
from PIL import Image, ImageTk
import mediapipe as mp
import os

import traceback

import warnings
warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype.*", category=UserWarning)

# ================================================================
# CONFIG SERVIDOR ESP32
# ================================================================
#ESP32_IP = "192.168.10.175" #Old IP
ESP32_IP = "192.168.10.106"
PORT = 12345

# ================================================================
# VARIABLES GLOBALES
# ================================================================
latest_frame = None
running = True

# GESTOS INDEPENDIENTES
latest_left_code = "1"
latest_left_name = "Quieto"
latest_right_code = "1"
latest_right_name = "Quieto"

client = None
connected = False
manual_mode = True
connection_in_progress = False

frame_lock = threading.Lock()
gesture_lock = threading.Lock()
landmark_lock = threading.Lock()

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# Últimos landmarks detectados (para dibujar en la vista)
latest_pose_landmarks = None

# FREEZE SYSTEM (para evitar falsos positivos cruzados)
freeze_left = False
freeze_right = False

# Calibration Request
calibration_requested = False
calibration_lock = threading.Lock()

def request_calibration():
    global calibration_requested
    with calibration_lock:
        calibration_requested = True
    print("[BodyControl] Calibration requested")


# ================================================================
# COLORES ESTILO EVANGELION
# ================================================================
bg_color        = "#05040a"
panel_color     = "#141020"
neon_blue       = "#7ae0ff"
neon_purple     = "#8f3cff"
neon_green      = "#7CFF4F"
neon_orange     = "#ff9e00"
neon_red        = "#ff0055"
text_color      = "#f0f0f0"
button_bg       = "#1b1828"
button_border   = neon_purple

# ================================================================
# TKINTER UI
# ================================================================
root = Tk()
root.title("EVA-01 REMOTE LINK")
root.configure(bg=bg_color)

main_frame = Frame(root, bg=bg_color)
main_frame.pack(padx=20, pady=20)

# --- prevent layout resizing when content changes ---
main_frame.pack_propagate(False)

# ------------------ CAMARA ------------------
camera_border = Frame(main_frame, bg=neon_purple, bd=4, relief="solid")
camera_border.grid(row=0, column=0, padx=20)

camera_label = Label(camera_border, bg="black")
camera_label.pack()

# ------------------ PANEL CONTROL ------------------
control_frame = Frame(
    main_frame, padx=20, pady=20,
    bg=panel_color, bd=4, relief="solid",
    highlightbackground=neon_green, highlightthickness=2
)
control_frame.grid(row=0, column=1, sticky="n")

Label(
    control_frame,
    text="EVA CONTROL PANEL",
    font=("Consolas", 18, "bold"),
    fg=neon_orange,
    bg=panel_color
).grid(row=0, column=0, columnspan=3, pady=(0, 5))

Label(
    control_frame,
    text="SYSTEM STATUS: NORMAL",
    font=("Consolas", 10, "bold"),
    fg=neon_green,
    bg=panel_color
).grid(row=1, column=0, columnspan=3, pady=(0, 10))

# ================================================================
# Button Calibration (in control panel)
# ================================================================
btn_calibrate = Button(
    control_frame,
    text="CALIBRAR (BASELINE)",
    command=request_calibration,
    width=18,
    bg=button_bg,
    fg=neon_orange,
    font=("Consolas", 11, "bold"),
    highlightbackground=neon_orange,
    highlightthickness=2,
    bd=0
)
# Place it under the connect/status row
btn_calibrate.grid(row=7, column=0, columnspan=3, pady=(5, 10))

# ================================================================
# MODO MANUAL
# ================================================================
manual_var = BooleanVar(value=True)

def force_neutral():
    global latest_left_code, latest_left_name
    global latest_right_code, latest_right_name

    with gesture_lock:
        latest_left_code  = "1"
        latest_left_name  = "Neutral"
        latest_right_code = "1"
        latest_right_name = "Neutral"

def toggle_manual():
    global manual_mode
    manual_mode = manual_var.get()

    # Always force a neutral command when switching modes
    force_neutral()

    if manual_mode:
        print("[MODE] Switched to MANUAL → sending NEUTRAL")
    else:
        print("[MODE] Switched to CAMERA → sending NEUTRAL")

manual_check = Checkbutton(
    control_frame,
    text="Modo manual (No envia gestos automaticos)",
    variable=manual_var,
    command=toggle_manual,
    fg=neon_green,
    bg=panel_color,
    selectcolor=panel_color,
    font=("Consolas", 11),
    activebackground=panel_color,
    activeforeground=neon_green
)
manual_check.grid(row=2, column=0, columnspan=3, pady=10)

# ================================================================
# FUNCION AUXILIAR PARA BOTONES
# ================================================================
def make_dpad_button(parent, text):
    return Button(
        parent,
        text=text,
        width=8,
        height=1,
        bg=button_bg,
        fg=neon_purple,
        activebackground="#261b3a",
        activeforeground=neon_blue,
        highlightbackground=button_border,
        highlightthickness=2,
        bd=0,
        font=("Consolas", 10, "bold"),
        relief="flat"
    )

# ================================================================
# PANEL MOVIMIENTOS LINEALES (SERVOS 1 y 2)
# ================================================================
lineal_frame = Frame(control_frame, bg=panel_color)
lineal_frame.grid(row=3, column=0, columnspan=3, pady=(5, 10))

Label(
    lineal_frame,
    text="MOVIMIENTOS LINEALES (Servos 1 y 2)",
    font=("Consolas", 11, "bold"),
    fg=neon_blue,
    bg=panel_color
).grid(row=0, column=0, columnspan=3, pady=(0, 5))

def set_left_manual(code, name):
    global latest_left_code, latest_left_name
    if not manual_mode:
        return
    with gesture_lock:
        latest_left_code = code
        latest_left_name = name

def reset_left(event=None):
    global latest_left_code, latest_left_name
    if not manual_mode:
        return
    with gesture_lock:
        latest_left_code = "1"
        latest_left_name = "Quieto"

btn_lin_up     = make_dpad_button(lineal_frame, "ADELANTE")
btn_lin_left   = make_dpad_button(lineal_frame, "IZQ")
btn_lin_center = make_dpad_button(lineal_frame, "QUIETO")
btn_lin_right  = make_dpad_button(lineal_frame, "DER")
btn_lin_down   = make_dpad_button(lineal_frame, "ATRAS")

btn_lin_up.grid(row=1, column=1)
btn_lin_left.grid(row=2, column=0)
btn_lin_center.grid(row=2, column=1)
btn_lin_right.grid(row=2, column=2)
btn_lin_down.grid(row=3, column=1)

btn_lin_up.bind("<ButtonPress-1>",   lambda e: set_left_manual("2", "Adelante"))
btn_lin_left.bind("<ButtonPress-1>", lambda e: set_left_manual("3", "Izquierda"))
btn_lin_right.bind("<ButtonPress-1>",lambda e: set_left_manual("4", "Derecha"))
btn_lin_down.bind("<ButtonPress-1>", lambda e: set_left_manual("5", "Atras"))
btn_lin_center.bind("<ButtonPress-1>", lambda e: set_left_manual("1", "Quieto"))

btn_lin_up.bind("<ButtonRelease-1>",     reset_left)
btn_lin_left.bind("<ButtonRelease-1>",   reset_left)
btn_lin_right.bind("<ButtonRelease-1>",  reset_left)
btn_lin_down.bind("<ButtonRelease-1>",   reset_left)
btn_lin_center.bind("<ButtonRelease-1>", reset_left)

# ================================================================
# BOTONES ESPECIALES: GESTO A y GESTO B
# ================================================================
Label(
    lineal_frame,
    text="GESTOS ESPECIALES",
    font=("Consolas", 11, "bold"),
    fg=neon_orange,
    bg=panel_color
).grid(row=4, column=0, columnspan=3, pady=(10, 5))

def set_gesto_A(event=None):
    if not manual_mode:
        return
    with gesture_lock:
        global latest_left_code, latest_left_name, latest_right_code, latest_right_name
        latest_left_code  = "A"
        latest_left_name  = "Gesto A"
        latest_right_code = "A"
        latest_right_name = "Gesto A"

def set_gesto_B(event=None):
    if not manual_mode:
        return
    with gesture_lock:
        global latest_left_code, latest_left_name, latest_right_code, latest_right_name
        latest_left_code  = "B"
        latest_left_name  = "Gesto B"
        latest_right_code = "B"
        latest_right_name = "Gesto B"

def reset_gestos(event=None):
    if not manual_mode:
        return
    with gesture_lock:
        global latest_left_code, latest_left_name, latest_right_code, latest_right_name
        latest_left_code  = "1"
        latest_left_name  = "Quieto"
        latest_right_code = "1"
        latest_right_name = "Quieto"

btn_gestoA = make_dpad_button(lineal_frame, "GESTO A")
btn_gestoB = make_dpad_button(lineal_frame, "GESTO B")

btn_gestoA.grid(row=5, column=0, pady=5)
btn_gestoB.grid(row=5, column=2, pady=5)

btn_gestoA.bind("<ButtonPress-1>", set_gesto_A)
btn_gestoA.bind("<ButtonRelease-1>", reset_gestos)
btn_gestoB.bind("<ButtonPress-1>", set_gesto_B)
btn_gestoB.bind("<ButtonRelease-1>", reset_gestos)

# ================================================================
# PANEL ROTACIONES (SERVOS 3 y 4)
# ================================================================
rot_frame = Frame(control_frame, bg=panel_color)
rot_frame.grid(row=4, column=0, columnspan=3, pady=(5, 10))

Label(
    rot_frame,
    text="ROTACIONES (Servos 3 y 4)",
    font=("Consolas", 11, "bold"),
    fg=neon_green,
    bg=panel_color
).grid(row=0, column=0, columnspan=3)

def set_right_manual(code, name):
    global latest_right_code, latest_right_name
    if not manual_mode:
        return
    with gesture_lock:
        latest_right_code = code
        latest_right_name = name

def reset_right(event=None):
    global latest_right_code, latest_right_name
    if not manual_mode:
        return
    with gesture_lock:
        latest_right_code = "1"
        latest_right_name = "Quieto"

btn_rot_up     = make_dpad_button(rot_frame, "ARRIBA")
btn_rot_left   = make_dpad_button(rot_frame, "IZQ")
btn_rot_center = make_dpad_button(rot_frame, "QUIETO")
btn_rot_right  = make_dpad_button(rot_frame, "DER")
btn_rot_down   = make_dpad_button(rot_frame, "ABAJO")

btn_rot_up.grid(row=1, column=1)
btn_rot_left.grid(row=2, column=0)
btn_rot_center.grid(row=2, column=1)
btn_rot_right.grid(row=2, column=2)
btn_rot_down.grid(row=3, column=1)

btn_rot_up.bind("<ButtonPress-1>",    lambda e: set_right_manual("2", "Arriba"))
btn_rot_left.bind("<ButtonPress-1>",  lambda e: set_right_manual("3", "Izquierda"))
btn_rot_right.bind("<ButtonPress-1>", lambda e: set_right_manual("4", "Derecha"))
btn_rot_down.bind("<ButtonPress-1>",  lambda e: set_right_manual("5", "Abajo"))
btn_rot_center.bind("<ButtonPress-1>",lambda e: set_right_manual("1", "Quieto"))

btn_rot_up.bind("<ButtonRelease-1>",     reset_right)
btn_rot_left.bind("<ButtonRelease-1>",   reset_right)
btn_rot_right.bind("<ButtonRelease-1>",  reset_right)
btn_rot_down.bind("<ButtonRelease-1>",   reset_right)
btn_rot_center.bind("<ButtonRelease-1>", reset_right)

# ================================================================
# RETROALIMENTACION
# ================================================================
feedback_label = Label(
    control_frame,
    text="Brazo izq: Quieto | Brazo der: Quieto [Auto]",
    font=("Consolas", 12),
    fg=neon_blue,
    bg=panel_color,
    justify="left",
    width=60,
    anchor="w"
)
feedback_label.grid(row=5, column=0, columnspan=3, pady=10)

# ================================================================
# ESTADO DE CONEXION
# ================================================================
status_frame = Frame(control_frame, bg=panel_color)
status_frame.grid(row=6, column=0, columnspan=3, pady=10)

status_light = Label(status_frame, text="●", font=("Consolas", 22),
                     fg=neon_red, bg=panel_color)
status_light.grid(row=0, column=0)

status_text = Label(status_frame, text="LINK: OFFLINE",
                    font=("Consolas", 12, "bold"),
                    fg=text_color, bg=panel_color)
status_text.grid(row=0, column=1, padx=10)

btn_connect = Button(
    status_frame,
    text="CONECTAR",
    width=12,
    bg=button_bg,
    fg=neon_blue,
    font=("Consolas", 11, "bold"),
    highlightbackground=neon_blue,
    highlightthickness=2,
    bd=0
)
btn_connect.grid(row=0, column=2, padx=10)

# ================================================================
# TUTORIAL EN DOS COLUMNAS (INCLUYE GESTO A Y B)
# ================================================================
# tutorial_container = Frame(main_frame, bg=bg_color)
# tutorial_container.grid(row=1, column=0, columnspan=2, pady=(20, 0), sticky="nsew")

# canvas = Canvas(tutorial_container, bg=bg_color, highlightthickness=0)
# scrollbar = Scrollbar(tutorial_container, orient="vertical", command=canvas.yview)
# canvas.configure(yscrollcommand=scrollbar.set)

# scrollbar.pack(side="right", fill="y")
# canvas.pack(side="left", fill="both", expand=True)

# scroll_frame = Frame(canvas, bg=bg_color)
# canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

# tutorial_images = []

# def load_tutorial_images():
#     BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#     figuras = [
#         ("fig1_quieto.png",   "Izq: Quieto",
#          "Brazo izquierdo relajado hacia abajo.",
#          "fig6_quietoR.png",  "Der: Quieto",
#          "Brazo derecho relajado hacia abajo."),

#         ("fig2_izquierda.png","Izq: Izquierda",
#          "Extiende el brazo izquierdo hacia la izquierda.",
#          "fig7_izquierdaR.png","Der: Izquierda",
#          "Cruza brazo derecho hacia la izquierda."),

#         ("fig3_derecha.png",  "Izq: Derecha",
#          "Cruza el brazo izquierdo hacia la derecha.",
#          "fig8_derechaR.png", "Der: Derecha",
#          "Extiende brazo derecho hacia la derecha."),

#         ("fig4_adelante.png", "Izq: Adelante",
#          "Levanta brazo izquierdo al frente.",
#          "fig9_arribaR.png",  "Der: Arriba",
#          "Levanta el brazo derecho completamente hacia arriba."),

#         ("fig5_atras.png",    "Izq: Atras",
#          "Lleva brazo izquierdo hacia tu espalda o hombro.",
#          "fig10_abajoR.png",  "Der: Abajo",
#          "Lleva brazo derecho hacia atrás o cintura."),

#         # Gesto A y Gesto B
#         ("fig11_gestoA.png",  "Gesto A",
#          "Alce ambos brazos para ejecutar el Gesto A.",
#          "fig12_gestoB.png",  "Gesto B",
#          "Retraiga ambos brazos hacia el cuerpo de forma que las manos casi toquen los hombros.")
#     ]

#     Label(
#         scroll_frame,
#         text="TUTORIAL DE POSTURAS — EVA LINK",
#         font=("Consolas", 17, "bold"),
#         fg=neon_orange,
#         bg=bg_color
#     ).grid(row=0, column=0, columnspan=2, pady=(0, 20))

#     row = 1
#     for izq_img, izq_title, izq_desc, der_img, der_title, der_desc in figuras:

#         cardL = Frame(scroll_frame, bg=panel_color, bd=2,
#                       highlightbackground=neon_purple, highlightthickness=2)
#         cardL.grid(row=row, column=0, padx=20, pady=10, sticky="n")

#         try:
#             imgL = cv2.imread(os.path.join(BASE_DIR, izq_img))
#             imgL = cv2.resize(imgL, (220, 220))
#             imgL = cv2.cvtColor(imgL, cv2.COLOR_BGR2RGB)
#             imgL = ImageTk.PhotoImage(Image.fromarray(imgL))
#             tutorial_images.append(imgL)
#             Label(cardL, image=imgL, bg=panel_color).pack(pady=(10, 5))
#         except:
#             Label(cardL, text=f"[No {izq_img}]", fg=neon_red, bg=panel_color).pack()

#         Label(cardL, text=izq_title, font=("Consolas", 13, "bold"),
#               fg=neon_blue, bg=panel_color).pack()
#         Label(cardL, text=izq_desc, wraplength=230, justify="left",
#               font=("Consolas", 11), fg=text_color, bg=panel_color).pack(pady=(0, 10))

#         cardR = Frame(scroll_frame, bg=panel_color, bd=2,
#                       highlightbackground=neon_purple, highlightthickness=2)
#         cardR.grid(row=row, column=1, padx=20, pady=10, sticky="n")

#         try:
#             imgR = cv2.imread(os.path.join(BASE_DIR, der_img))
#             imgR = cv2.resize(imgR, (220, 220))
#             imgR = cv2.cvtColor(imgR, cv2.COLOR_BGR2RGB)
#             imgR = ImageTk.PhotoImage(Image.fromarray(imgR))
#             tutorial_images.append(imgR)
#             Label(cardR, image=imgR, bg=panel_color).pack(pady=(10, 5))
#         except:
#             Label(cardR, text=f"[No {der_img}]", fg=neon_red, bg=panel_color).pack()

#         Label(cardR, text=der_title, font=("Consolas", 13, "bold"),
#               fg=neon_blue, bg=panel_color).pack()
#         Label(cardR, text=der_desc, wraplength=230, justify="left",
#               font=("Consolas", 11), fg=text_color, bg=panel_color).pack(pady=(0, 10))

#         row += 1

#     scroll_frame.update_idletasks()
#     canvas.config(scrollregion=canvas.bbox("all"))

# load_tutorial_images()

# ================================================================
# CONEXIÓN CON ESP32
# ================================================================
def connect_worker():
    global client, connected, connection_in_progress

    connection_in_progress = True
    print("[CONNECT] Starting connection attempts...")

    for i in range(30):
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.settimeout(2)  # a bit more generous
            c.connect((ESP32_IP, PORT))
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            c.settimeout(None)

            client = c
            connected = True
            print(f"[CONNECT] Connected to ESP32 on attempt {i+1}")
            break
        except Exception as e:
            connected = False
            print(f"[CONNECT] Attempt {i+1} failed:", e)
            time.sleep(0.5)
    else:
        print("[CONNECT] Failed to connect after 30 attempts")

    connection_in_progress = False


def toggle_connection():
    global client, connected, connection_in_progress

    # If already connected: disconnect
    if connected:
        print("[CONNECT] Closing connection")
        try:
            client.close()
        except:
            pass
        client = None
        connected = False
        return

    # Avoid starting multiple simultaneous connection threads
    if connection_in_progress:
        print("[CONNECT] Connection already in progress")
        return

    # Start background thread for connection attempts
    threading.Thread(target=connect_worker, daemon=True).start()


btn_connect.config(command=toggle_connection)

# ================================================================
# HILO ENVÍO Y RECIBIDO
# ================================================================
def communication_thread():
    global client, connected, running
    global latest_left_code, latest_right_code

    prev_L = None
    prev_R = None
    was_connected = False

    HEARTBEAT_INTERVAL = 0.5  # seconds
    last_send = 0.0

    while running:
        if connected and client:
            try:
                with gesture_lock:
                    L = latest_left_code
                    R = latest_right_code

                # Only send if:
                #  - connection just became active, or
                #  - the command changed
                if (not was_connected) or (L != prev_L) or (R != prev_R):
                    if L == "A" and R == "A":
                        msg = "A,A\n"
                    elif L == "B" and R == "B":
                        msg = "B,B\n"
                    else:
                        msg = f"R{R},L{L}\n"

                    client.send(msg.encode())

                    prev_L, prev_R = L, R

                was_connected = True

            except Exception as e:
                print("[SEND] Error:", e)
                try:
                    client.close()
                except:
                    pass
                client = None
                connected = False
                was_connected = False
        else:
            was_connected = False

        time.sleep(0.01)

def receive_thread():
    global client, connected, running
    while running:
        if connected and client:
            try:
                data = client.recv(1024)
                if not data:
                    # Connection closed gracefully
                    print("[RECV] ESP32 closed the connection")
                    try:
                        client.close()
                    except:
                        pass
                    client = None
                    connected = False
                else:
                    # If you want debug:
                    # print("ESP32:", data.decode(errors="ignore").strip())
                    pass
            except Exception as e:
                # Any recv error: treat as broken connection
                print("[RECV] Error:", e)
                try:
                    client.close()
                except:
                    pass
                client = None
                connected = False
        time.sleep(0.05)



# ================================================================
# HILO CÁMARA
# ================================================================
def camera_thread():
    global latest_frame, running

    cap = cv2.VideoCapture(0) #Built-in camera
    #cap = cv2.VideoCapture(1) #External camera
    cap.set(3, 640)
    cap.set(4, 360)

    if not cap.isOpened():
        print("No se pudo abrir la cámara.")
        running = False
        return

    while running:
        ret, frame = cap.read()
        if ret:
            with frame_lock:
                latest_frame = frame
        time.sleep(0.01)

    cap.release()

# ================================================================
# DETECCIÓN MEDIAPIPE (freeze bilateral + Gesto A/B auto)
# ================================================================
import time
from collections import deque
import math

# persistent lockout to avoid A → B confusion
_last_raise_time = 0.0

# -----------------------
# Lean toggle controls
# -----------------------
lean_enabled = False  # default OFF

def toggle_lean():
    global lean_enabled
    lean_enabled = not lean_enabled
    print(f"[BodyControl] lean_enabled = {lean_enabled}")

def set_lean_enabled(value: bool):
    global lean_enabled
    lean_enabled = bool(value)
    print(f"[BodyControl] lean_enabled = {lean_enabled}")


def body_control_thread():
    """
    Body-only locomotion + walk-in-place + optional lean + right-hand gestures:

    Locomotion:
      - Yaw right     -> R4,L1
      - Yaw left      -> R3,L1
      - Walk-in-place -> R1,L2   (forward intent)
      - Lean forward  -> R1,L2   (only if lean_enabled == True)
      - Lean back     -> R1,L5   (only if lean_enabled == True)
      - Neutral       -> R1,L1

    Right-hand gestures override locomotion:
      - Right hand raised  -> A,A
      - Right hand forward -> B,B
    """
    global latest_left_code, latest_left_name
    global latest_right_code, latest_right_name
    global manual_mode, latest_pose_landmarks
    global lean_enabled
    global calibration_requested, calibration_lock

    # -----------------------
    # Tunable parameters
    # -----------------------
    EMA_ALPHA = 0.35

    # Yaw hysteresis
    YAW_ON  = 0.08
    YAW_OFF = 0.05

    # Lean hysteresis
    LEAN_ON  = 0.12
    LEAN_OFF = 0.08

    # Flip if directions are backwards (camera mirroring)
    YAW_SIGN  = 1.0
    LEAN_SIGN = -1.0

    # Roll (lean left/right) hysteresis (normalized)
    ROLL_ON  = 0.35
    ROLL_OFF = 0.25
    ROLL_SIGN = -1.0  # flip if left/right is inverted

    roll0 = 0.0
    roll_s = None


    # -----------------------
    # Right-hand gesture parameters (override locomotion)
    # -----------------------
    GESTURE_DEBOUNCE_FRAMES = 16   # must be true N frames before activating
    GESTURE_RELEASE_FRAMES  = 8   # must be false N frames before releasing

    RIGHT_HAND_RAISE_DY = 0.10    # wrist above shoulder by this much (normalized coords)
    RIGHT_HAND_FWD_DZ   = 0.20    # wrist toward camera compared to shoulder (z units)

    # -----------------------
    # Walk-in-place parameters
    # -----------------------
    WIP_WINDOW_S = 1.2
    WIP_MIN_FLIPS = 3
    WIP_AMP_ON = 0.18
    WIP_AMP_OFF = 0.12
    WIP_EMA_ALPHA = 0.30

    # Baselines (neutral pose)
    yaw0 = 0.0
    lean0 = 0.0

    # Smoothed signals
    yaw_s = None
    lean_s = None

    # State (hysteresis)
    state = "NEUTRAL"  # "TURN_L", "TURN_R", "LEAN_L", "LEAN_R", "FWD", "BACK", "NEUTRAL"

    # Walk-in-place state
    wip_d_s = None
    wip_last_sign = 0
    wip_flip_times = deque()
    wip_amp_hist = deque()
    wip_amp_times = deque()
    wip_active = False

    # Right-hand gesture state
    a_on_count = 0
    a_off_count = 0
    b_on_count = 0
    b_off_count = 0
    active_gesture = None  # None, "A", "B"

    def ema(prev, new, a):
        return new if prev is None else (a * new + (1.0 - a) * prev)

    def avg3(a, b):
        return ((a.x + b.x) * 0.5, (a.y + b.y) * 0.5, (a.z + b.z) * 0.5)

    def compute_yaw_lean_roll(lm):
        shL, shR = lm[11], lm[12]
        hipL, hipR = lm[23], lm[24]

        sh_c = avg3(shL, shR)
        hip_c = avg3(hipL, hipR)

        # Yaw proxy (depth difference)
        yaw_raw = (shR.z - shL.z) * YAW_SIGN

        # Forward/back lean (depth-based is more reliable than y-based)
        lean_raw = (hip_c[2] - sh_c[2]) * LEAN_SIGN

        # Roll proxy (side lean), normalized by shoulder width
        shoulder_w = abs(shR.x - shL.x)
        if shoulder_w < 1e-6:
            roll_raw = 0.0
        else:
            shoulder_tilt = (shL.y - shR.y)
            hip_tilt      = (hipL.y - hipR.y)
            roll_raw = ((shoulder_tilt - hip_tilt) / shoulder_w) * ROLL_SIGN

        return yaw_raw, lean_raw, roll_raw, sh_c, hip_c

    def detect_right_hand_gesture(lm):
        """
        Returns: None, "A", or "B"
        A = right hand raised
        B = right hand forward (deliberate push)
        """
        global _last_raise_time

        sh = lm[12]   # right shoulder
        el = lm[14]   # right elbow
        wr = lm[16]   # right wrist

        # Arm vector (shoulder -> wrist)
        dx = wr.x - sh.x
        dy = wr.y - sh.y
        dz = wr.z - sh.z

        # ---------
        # Angles
        # ---------
        # Elevation: how much the arm points UP
        elev = math.degrees(
            math.atan2(-dy, math.sqrt(dx*dx + dz*dz) + 1e-9)
        )

        # Forward: how much the arm points TOWARD CAMERA
        fwd = math.degrees(
            math.atan2(-dz, math.sqrt(dx*dx + dy*dy) + 1e-9)
        )

        # Elbow extension angle (straight arm check)
        def angle_3pts(a, b, c):
            ab = (a.x-b.x, a.y-b.y, a.z-b.z)
            cb = (c.x-b.x, c.y-b.y, c.z-b.z)
            dot = ab[0]*cb[0] + ab[1]*cb[1] + ab[2]*cb[2]
            nab = math.sqrt(ab[0]**2 + ab[1]**2 + ab[2]**2) + 1e-9
            ncb = math.sqrt(cb[0]**2 + cb[1]**2 + cb[2]**2) + 1e-9
            cosang = max(-1.0, min(1.0, dot/(nab*ncb)))
            return math.degrees(math.acos(cosang))

        elbow = angle_3pts(sh, el, wr)

        # ---------
        # Tunables (start here)
        # ---------
        ELEV_ON   = 35    # degrees → clearly raised
        FWD_ON    = 3205    # degrees → clearly forward
        ELBOW_ON  = 135   # degrees → arm fairly straight
        RAISE_LOCK = 0.35 # seconds

        ELEV_UP_MIN = 10      # degrees (above shoulder line)
        ELEV_DOWN_MAX = -15  # degrees (below shoulder line)

        FWD_MIN = 25         # degrees


        now = time.time()

        print(
            f"elev={elev:.1f}°  fwd={fwd:.1f}°  elbow={elbow:.1f}°",
            end="\r"
        )

        # ---------
        # Gesture A: RAISE (wins)
        # ---------
        if elev > ELEV_UP_MIN and fwd > FWD_MIN:
            _last_raise_time = now
            return "A"

        # Ignore forward shortly after a raise motion
        if (now - _last_raise_time) < RAISE_LOCK:
            return None

        # ---------
        # Gesture B: FORWARD (deliberate push)
        # ---------
        if elev < ELEV_DOWN_MAX and fwd > FWD_MIN:
            return "B"

        return None

    def update_walk_in_place(lm, sh_c, hip_c):
        nonlocal wip_d_s, wip_last_sign, wip_active
        now = time.time()

        ankL, ankR = lm[27], lm[28]

        dx = sh_c[0] - hip_c[0]
        dy = sh_c[1] - hip_c[1]
        scale = (dx * dx + dy * dy) ** 0.5
        if scale < 1e-6:
            return False

        liftL = (hip_c[1] - ankL.y) / scale
        liftR = (hip_c[1] - ankR.y) / scale

        d = liftL - liftR
        wip_d_s = ema(wip_d_s, d, WIP_EMA_ALPHA)
        dabs = abs(wip_d_s)

        wip_amp_hist.append(dabs)
        wip_amp_times.append(now)

        sign = 1 if wip_d_s > 0 else (-1 if wip_d_s < 0 else 0)
        if sign != 0 and wip_last_sign != 0 and sign != wip_last_sign:
            wip_flip_times.append(now)
        if sign != 0:
            wip_last_sign = sign

        while wip_flip_times and (now - wip_flip_times[0]) > WIP_WINDOW_S:
            wip_flip_times.popleft()
        while wip_amp_times and (now - wip_amp_times[0]) > WIP_WINDOW_S:
            wip_amp_times.popleft()
            wip_amp_hist.popleft()

        flips = len(wip_flip_times)
        amp_peak = max(wip_amp_hist) if wip_amp_hist else 0.0

        if wip_active:
            if flips < 2 or amp_peak < WIP_AMP_OFF:
                wip_active = False
        else:
            if flips >= WIP_MIN_FLIPS and amp_peak >= WIP_AMP_ON:
                wip_active = True

        return wip_active

    with mp_pose.Pose(
        model_complexity=0,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    ) as pose:

        # -----------------------
        # Calibration (~1s neutral)
        # -----------------------
        neutral_yaw = []
        neutral_lean = []
        neutral_roll = []

        calib_start = time.time()

        while running and (time.time() - calib_start) < 1.0:
            if latest_frame is None or manual_mode:
                time.sleep(0.02)
                continue

            with frame_lock:
                frame = latest_frame.copy()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            if results.pose_landmarks:
                with landmark_lock:
                    latest_pose_landmarks = results.pose_landmarks

                lm = results.pose_landmarks.landmark
                y_raw, l_raw, r_raw, _, _ = compute_yaw_lean_roll(lm)
                neutral_yaw.append(y_raw)
                neutral_lean.append(l_raw)
                neutral_roll.append(r_raw)

            time.sleep(0.02)

        yaw0 = (sum(neutral_yaw) / len(neutral_yaw)) if neutral_yaw else 0.0
        lean0 = (sum(neutral_lean) / len(neutral_lean)) if neutral_lean else 0.0
        roll0 = (sum(neutral_roll) / len(neutral_roll)) if neutral_roll else 0.0

        # -----------------------
        # Main loop
        # -----------------------
        while running:
            # -----------------------
            # Recalibration check
            # -----------------------
            do_calib = False
            with calibration_lock:
                if calibration_requested:
                    do_calib = True

            if do_calib:
                # Clear request immediately (so it doesn't repeat)
                with calibration_lock:
                    calibration_requested = False

                # Optional: force safe outputs during calibration
                with gesture_lock:
                    latest_left_code = "1"
                    latest_left_name = "Calibrating..."
                    latest_right_code = "1"
                    latest_right_name = "Calibrating..."

                # Reset “stateful” filters so calibration feels immediate
                yaw_s = None
                lean_s = None
                state = "NEUTRAL"

                # Reset WIP state (important)
                wip_d_s = None
                wip_last_sign = 0
                wip_flip_times.clear()
                wip_amp_hist.clear()
                wip_amp_times.clear()
                wip_active = False

                # Reset right-hand gesture state (important)
                a_on_count = a_off_count = 0
                b_on_count = b_off_count = 0
                active_gesture = None

                # Collect new baselines (~1s)
                neutral_yaw = []
                neutral_lean = []
                neutral_roll = []
                calib_start = time.time()

                while running and (time.time() - calib_start) < 1.0:
                    if latest_frame is None or manual_mode:
                        time.sleep(0.02)
                        continue

                    with frame_lock:
                        frame = latest_frame.copy()

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = pose.process(rgb)

                    if results.pose_landmarks:
                        with landmark_lock:
                            latest_pose_landmarks = results.pose_landmarks

                        lm = results.pose_landmarks.landmark
                        y_raw, l_raw, r_raw, *_ = compute_yaw_lean_roll(lm)
                        neutral_yaw.append(y_raw)
                        neutral_lean.append(l_raw)
                        neutral_roll.append(r_raw)
                        
                    time.sleep(0.02)

                yaw0 = (sum(neutral_yaw) / len(neutral_yaw)) if neutral_yaw else yaw0
                lean0 = (sum(neutral_lean) / len(neutral_lean)) if neutral_lean else lean0
                roll0 = (sum(neutral_roll) / len(neutral_roll)) if neutral_roll else roll0

                print(f"[BodyControl] Recalibrated yaw0={yaw0:.4f}, lean0={lean0:.4f}, roll0={roll0:.4f}")
                continue  # skip rest of this loop iteration

            if latest_frame is None or manual_mode:
                time.sleep(0.02)
                continue

            with frame_lock:
                frame = latest_frame.copy()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            if results.pose_landmarks:
                with landmark_lock:
                    latest_pose_landmarks = results.pose_landmarks

                lm = results.pose_landmarks.landmark

                # =====================================================
                # RIGHT-HAND GESTURE OVERRIDE (A,A / B,B)
                # =====================================================
                g = detect_right_hand_gesture(lm)

                # Update debounce counters
                if g == "A":
                    a_on_count += 1
                    a_off_count = 0
                else:
                    a_off_count += 1
                    a_on_count = 0

                if g == "B":
                    b_on_count += 1
                    b_off_count = 0
                else:
                    b_off_count += 1
                    b_on_count = 0

                # Activate gesture if held long enough
                if active_gesture is None:
                    if a_on_count >= GESTURE_DEBOUNCE_FRAMES:
                        active_gesture = "A"
                    elif b_on_count >= GESTURE_DEBOUNCE_FRAMES:
                        active_gesture = "B"
                else:
                    # Release gesture when gone long enough
                    if active_gesture == "A" and a_off_count >= GESTURE_RELEASE_FRAMES:
                        active_gesture = None
                    elif active_gesture == "B" and b_off_count >= GESTURE_RELEASE_FRAMES:
                        active_gesture = None

                # If gesture active, override & skip locomotion
                if active_gesture == "A":
                    with gesture_lock:
                        latest_left_code  = "A"
                        latest_left_name  = "Gesture A (R hand up)"
                        latest_right_code = "A"
                        latest_right_name = "Gesture A (R hand up)"
                    time.sleep(0.02)
                    continue

                if active_gesture == "B":
                    with gesture_lock:
                        latest_left_code  = "B"
                        latest_left_name  = "Gesture B (R hand forward)"
                        latest_right_code = "B"
                        latest_right_name = "Gesture B (R hand forward)"
                    time.sleep(0.02)
                    continue

                # =====================================================
                # LOCOMOTION (yaw / wip / optional lean)
                # =====================================================
                yaw_raw, lean_raw, roll_raw, sh_c, hip_c = compute_yaw_lean_roll(lm)
                yaw = yaw_raw - yaw0
                lean = lean_raw - lean0
                roll = roll_raw - roll0

                yaw_s  = ema(yaw_s,  yaw,  EMA_ALPHA)
                lean_s = ema(lean_s, lean, EMA_ALPHA)
                roll_s = ema(roll_s, roll, EMA_ALPHA)

                wip = update_walk_in_place(lm, sh_c, hip_c)

                # Decide state (priority: yaw > roll > WIP > lean(if enabled))
                # 1) Turning
                if state in ("TURN_L", "TURN_R"):
                    if abs(yaw_s) < YAW_OFF:
                        state = "NEUTRAL"
                    else:
                        state = "TURN_R" if yaw_s > 0 else "TURN_L"
                else:
                    if abs(yaw_s) > YAW_ON:
                        state = "TURN_R" if yaw_s > 0 else "TURN_L"
                    else:
                        # 2) Roll (lean left/right)
                        if state in ("LEAN_L", "LEAN_R"):
                            if abs(roll_s) < ROLL_OFF:
                                state = "NEUTRAL"
                            else:
                                state = "LEAN_R" if roll_s > 0 else "LEAN_L"
                        else:
                            if abs(roll_s) > ROLL_ON:
                                state = "LEAN_R" if roll_s > 0 else "LEAN_L"
                            else:
                                # 3) Walk-in-place
                                if wip:
                                    state = "FWD"
                                else:
                                    # 4) Lean forward/back (optional)
                                    if not lean_enabled:
                                        state = "NEUTRAL"
                                    else:
                                        if state in ("FWD", "BACK"):
                                            if abs(lean_s) < LEAN_OFF:
                                                state = "NEUTRAL"
                                            else:
                                                state = "BACK" if lean_s > 0 else "FWD"
                                        else:
                                            if abs(lean_s) > LEAN_ON:
                                                state = "BACK" if lean_s > 0 else "FWD"
                                            else:
                                                state = "NEUTRAL"

                # Map state -> your R/L commands
                if state == "FWD":
                    # forward
                    codeR, nameR = "1", "Neutral"
                    codeL, nameL = "2", "Forward"

                elif state == "BACK":
                    codeR, nameR = "1", "Neutral"
                    codeL, nameL = "5", "Back"

                elif state == "TURN_R":
                    codeR, nameR = "4", "Turn Right"
                    codeL, nameL = "1", "Neutral"

                elif state == "TURN_L":
                    codeR, nameR = "3", "Turn Left"
                    codeL, nameL = "1", "Neutral"

                elif state == "LEAN_R":
                    # lean right -> R1,L4
                    codeR, nameR = "1", "Neutral"
                    codeL, nameL = "4", "Lean Right"

                elif state == "LEAN_L":
                    # lean left -> R1,L3
                    codeR, nameR = "1", "Neutral"
                    codeL, nameL = "3", "Lean Left"

                else:
                    codeR, nameR = "1", "Neutral"
                    codeL, nameL = "1", "Neutral"

                with gesture_lock:
                    latest_left_code = codeL
                    latest_left_name = nameL
                    latest_right_code = codeR
                    latest_right_name = nameR

            else:
                with landmark_lock:
                    latest_pose_landmarks = None
                with gesture_lock:
                    latest_left_code = "1"
                    latest_left_name = "Neutral"
                    latest_right_code = "1"
                    latest_right_name = "Neutral"

            #time.sleep(0.02)

# ================================================================
# UPDATE GUI
# ================================================================
def update_gui():
    global latest_frame, connected, running

    if latest_frame is not None:
        with frame_lock:
            frame = latest_frame.copy()

        # Draw pose landmarks if available and not in manual mode
        if not manual_mode:
            with landmark_lock:
                lm_to_draw = latest_pose_landmarks
            if lm_to_draw is not None:
                mp_drawing.draw_landmarks(
                    frame,
                    lm_to_draw,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style()
                )

        with gesture_lock:
            left_name  = latest_left_name
            left_code  = latest_left_code
            right_name = latest_right_name
            right_code = latest_right_code

        L_COLOR = (0, 0, 0)    # red in BGR
        R_COLOR = (0, 0, 0)    # green in BGR

        cv2.putText(frame, f"L: {left_name} ({left_code})", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, L_COLOR, 2)
        cv2.putText(frame, f"R: {right_name} ({right_code})", (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, R_COLOR, 2)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        imgtk = ImageTk.PhotoImage(Image.fromarray(frame))
        camera_label.config(image=imgtk)
        camera_label.imgtk = imgtk

    # Connection UI
    if connected:
        status_light.config(fg=neon_green)
        status_text.config(text="LINK: ONLINE")
        btn_connect.config(text="DESCONECTAR")
    else:
        status_light.config(fg=neon_red)
        status_text.config(text="LINK: OFFLINE")
        btn_connect.config(text="CONECTAR")

    # Feedback label
    with gesture_lock:
        feedback_label.config(
            text=f"L: {latest_left_name} | R: {latest_right_name} [{'Manual' if manual_mode else 'Auto'}]"
        )

    if running:
        root.after(10, update_gui)


# ================================================================
# INICIO HILOS
# ================================================================
threading.Thread(target=camera_thread, daemon=True).start()
threading.Thread(target=communication_thread, daemon=True).start()
threading.Thread(target=receive_thread, daemon=True).start()
threading.Thread(target=body_control_thread, daemon=True).start()

# ================================================================
# LOOP PRINCIPAL
# ================================================================
update_gui()
root.mainloop()
running = False
