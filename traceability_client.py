"""Cliente Tkinter para explorar la API de trazabilidad distribuida.

Permite enviar pedidos simulados, propagar un ``traceparent`` W3C y consultar
los spans almacenados por la API. La paleta toma como referencia los colores
institucionales del TecNM: azul marino, naranja, blanco y negro.

La aplicación solo utiliza la biblioteca estándar de Python. Primero inicia
la API desde la carpeta del proyecto:
    uvicorn traceability_main:app --reload

Después abre este cliente:
    python traceability_client.py
"""

import json
import math
import re
import secrets
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import messagebox, ttk


# Paleta de la interfaz: azul marino como base y naranja para las acciones.
NAVY = "#003B5C"
NAVY_DARK = "#002B45"
ORANGE = "#F28C28"
ORANGE_DARK = "#D87312"
WHITE = "#FFFFFF"
BLACK = "#171717"
LIGHT = "#F2F5F7"
MUTED = "#52616B"

# La API de demostración implementa el formato W3C traceparent versión 00.
TRACEPARENT_PATTERN = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)


class TraceabilityClientApp(tk.Tk):
    """Ventana principal para generar pedidos y revisar sus trazas."""

    def __init__(self) -> None:
        """Configura la ventana, los valores iniciales y los componentes."""
        super().__init__()
        self.title("TecNM | Cliente de Trazabilidad Distribuida")
        self.geometry("1366x768")
        self.minsize(1120, 680)
        self.configure(background=LIGHT)

        # Variables enlazadas a formularios Tk para leer y actualizar valores.
        self.api_url = tk.StringVar(value="http://127.0.0.1:8000")
        self.cliente_id = tk.StringVar(value="CLI-99412")
        self.metodo_pago = tk.StringVar(value="TARJETA_CREDITO")
        self.producto_id = tk.StringVar(value="PROD-8821")
        self.cantidad = tk.StringVar(value="2")
        self.precio_unitario = tk.StringVar(value="450.50")
        self.traceparent = tk.StringVar()
        self.trace_id = tk.StringVar()
        self.status = tk.StringVar(value="Listo para conectar con la API")
        self.action_buttons: list[ttk.Button] = []

        self._configure_styles()
        self._build_ui()

    def _configure_styles(self) -> None:
        """Define colores y tipografías de los widgets ttk."""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=LIGHT)
        style.configure("TLabel", background=LIGHT, foreground=BLACK, font=("Segoe UI", 10))
        style.configure(
            "Title.TLabel",
            background=NAVY,
            foreground=WHITE,
            font=("Segoe UI", 21, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=NAVY,
            foreground="#D9E7EF",
            font=("Segoe UI", 10),
        )
        style.configure(
            "TLabelframe",
            background=WHITE,
            bordercolor="#D5DEE4",
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=WHITE,
            foreground=NAVY,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TEntry",
            fieldbackground=WHITE,
            foreground=BLACK,
            padding=(7, 6),
        )
        style.configure(
            "Action.TButton",
            background=ORANGE,
            foreground=WHITE,
            font=("Segoe UI", 9, "bold"),
            padding=(12, 8),
            borderwidth=0,
        )
        style.map(
            "Action.TButton",
            background=[("active", ORANGE_DARK), ("disabled", "#C7CDD1")],
            foreground=[("disabled", "#68737A")],
        )
        style.configure(
            "Secondary.TButton",
            background=NAVY,
            foreground=WHITE,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7),
            borderwidth=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", NAVY_DARK), ("disabled", "#C7CDD1")],
            foreground=[("disabled", "#68737A")],
        )
        style.configure(
            "Status.TLabel",
            background=LIGHT,
            foreground=MUTED,
            font=("Segoe UI", 9),
        )

    def _build_ui(self) -> None:
        """Distribuye cabecera, conexión, formularios y salida de telemetría."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Cabecera institucional con el propósito didáctico de la herramienta.
        header = tk.Frame(self, background=NAVY, padx=22, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Trazabilidad distribuida",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="W3C Trace Context  ·  Spans jerárquicos  ·  Consulta de trazas",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        tk.Label(
            header,
            text="TecNM",
            background=NAVY,
            foreground=ORANGE,
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=1, rowspan=2, padx=(20, 6))

        # La dirección se puede cambiar para apuntar a otra instancia de la API.
        connection = ttk.Frame(self, padding=(18, 10))
        connection.grid(row=1, column=0, sticky="ew")
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="URL base de la API").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ttk.Entry(connection, textvariable=self.api_url).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(
            connection,
            text="FastAPI · puerto 8000 por defecto",
            foreground=MUTED,
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        content = ttk.Frame(self, padding=(18, 2, 18, 8))
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=4, uniform="panels")
        content.columnconfigure(1, weight=6, uniform="panels")
        content.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(content)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(1, weight=1)

        right_panel = ttk.Frame(content)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)

        self._build_order_form(left_panel)
        self._build_trace_controls(left_panel)
        self._build_results_panel(right_panel)

        footer = ttk.Frame(self, padding=(18, 0, 18, 10))
        footer.grid(row=3, column=0, sticky="ew")
        ttk.Separator(footer).pack(fill="x", pady=(0, 7))
        ttk.Label(footer, textvariable=self.status, style="Status.TLabel").pack(
            side="left"
        )
        ttk.Label(
            footer,
            text="Demostración educativa · los servicios y spans son simulados",
            style="Status.TLabel",
        ).pack(side="right")

    def _add_button(
        self,
        parent: ttk.Widget,
        text: str,
        command: Callable[[], None],
        *,
        secondary: bool = False,
    ) -> ttk.Button:
        """Crea y registra botones que se desactivan durante una solicitud HTTP."""
        style = "Secondary.TButton" if secondary else "Action.TButton"
        button = ttk.Button(parent, text=text, command=command, style=style)
        self.action_buttons.append(button)
        return button

    def _build_order_form(self, parent: ttk.Frame) -> None:
        """Construye el formulario para el endpoint de procesamiento de pedidos."""
        form = ttk.LabelFrame(
            parent, text="1 · Procesar pedido simulado", padding=14
        )
        form.grid(row=0, column=0, sticky="new", pady=(0, 10))
        form.columnconfigure(1, weight=1)

        ttk.Label(
            form,
            text=(
                "La API crea el span HTTP raíz y spans hijos de inventario y pagos. "
                "No se realizan transacciones reales."
            ),
            wraplength=440,
            foreground=MUTED,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        fields = (
            ("ID del cliente", self.cliente_id),
            ("Método de pago", self.metodo_pago),
            ("ID del producto", self.producto_id),
            ("Cantidad", self.cantidad),
            ("Precio unitario", self.precio_unitario),
        )
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(form, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=4
            )
            ttk.Entry(form, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=4
            )

        trace_frame = ttk.Frame(form)
        trace_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(9, 3))
        trace_frame.columnconfigure(0, weight=1)
        ttk.Label(trace_frame, text="traceparent entrante (opcional)").grid(
            row=0, column=0, sticky="w"
        )
        self._add_button(
            trace_frame,
            "Generar contexto",
            self._generate_traceparent,
            secondary=True,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Entry(form, textvariable=self.traceparent).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(3, 4)
        )

        ttk.Label(
            form,
            text=(
                "Si se proporciona, el Trace ID se conserva y el Span ID entrante "
                "se registra como padre del span HTTP."
            ),
            wraplength=440,
            foreground=MUTED,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 8))
        self._add_button(
            form, "Enviar pedido", self._submit_order
        ).grid(row=9, column=0, columnspan=2, sticky="ew")

    def _build_trace_controls(self, parent: ttk.Frame) -> None:
        """Añade acciones para listar spans y consultar un Trace ID específico."""
        frame = ttk.LabelFrame(
            parent, text="2 · Consultar trazas y spans", padding=14
        )
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text=(
                "Consulta el almacenamiento en memoria del proceso. Después de "
                "reiniciar la API, la colección comienza vacía."
            ),
            wraplength=440,
            foreground=MUTED,
        ).grid(row=0, column=0, sticky="w", pady=(0, 9))
        ttk.Label(frame, text="Trace ID").grid(
            row=1, column=0, sticky="w", pady=(0, 3)
        )
        ttk.Entry(frame, textvariable=self.trace_id).grid(
            row=2, column=0, sticky="ew"
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._add_button(
            buttons, "Consultar traza", self._get_trace
        ).pack(side="left", fill="x", expand=True)
        self._add_button(
            buttons, "Listar todos los spans", self._get_all_spans, secondary=True
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        ttk.Label(
            frame,
            text=(
                "Endpoints: POST /v1/pedidos/procesar · "
                "GET /v1/telemetry/trace/{trace_id} · "
                "GET /v1/telemetry/spans"
            ),
            wraplength=440,
            foreground=MUTED,
        ).grid(row=4, column=0, sticky="w", pady=(12, 0))

    def _build_results_panel(self, parent: ttk.Frame) -> None:
        """Crea el panel de respuesta con scroll para resultados JSON extensos."""
        frame = ttk.LabelFrame(parent, text="Respuesta y jerarquía de spans", padding=9)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.response_text = tk.Text(
            frame,
            wrap="word",
            state="disabled",
            background=WHITE,
            foreground=BLACK,
            insertbackground=BLACK,
            selectbackground=ORANGE,
            font=("Consolas", 10),
            padx=12,
            pady=10,
            relief="flat",
        )
        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.response_text.yview
        )
        self.response_text.configure(yscrollcommand=scrollbar.set)
        self.response_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._write_response(
            "Listo para explorar la traza.\n\n"
            "• Envía un pedido para generar un Trace ID y sus spans.\n"
            "• Usa «Generar contexto» para crear un traceparent W3C de entrada.\n"
            "• Consulta la traza por ID o lista todos los spans.\n\n"
            "Nota: la API mantiene spans en memoria; este cliente no se conecta "
            "a una instancia Jaeger real."
        )

    def _generate_traceparent(self) -> None:
        """Genera un contexto W3C versión 00 para simular una llamada upstream."""
        trace_id = secrets.token_hex(16)
        parent_span_id = secrets.token_hex(8)
        self.traceparent.set(f"00-{trace_id}-{parent_span_id}-01")
        self.status.set("Contexto W3C generado; se enviará con el siguiente pedido")

    def _submit_order(self) -> None:
        """Valida el pedido localmente y lo envía a la API."""
        customer_id = self.cliente_id.get().strip()
        payment_method = self.metodo_pago.get().strip()
        product_id = self.producto_id.get().strip()
        if not customer_id or not payment_method or not product_id:
            messagebox.showerror(
                "Datos incompletos",
                "Ingresa el ID del cliente, método de pago e ID del producto.",
                parent=self,
            )
            return

        try:
            quantity = int(self.cantidad.get())
            unit_price = float(self.precio_unitario.get())
            if quantity <= 0 or not math.isfinite(unit_price) or unit_price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Cantidad o precio inválido",
                "La cantidad debe ser un entero positivo y el precio un número positivo.",
                parent=self,
            )
            return

        headers: dict[str, str] = {}
        traceparent = self.traceparent.get().strip()
        if traceparent:
            if not self._is_valid_traceparent(traceparent):
                messagebox.showerror(
                    "traceparent inválido",
                    "Usa el formato W3C versión 00 con IDs hexadecimales no nulos.",
                    parent=self,
                )
                return
            headers["traceparent"] = traceparent

        self._start_request(
            "POST",
            "/v1/pedidos/procesar",
            payload={
                "cliente_id": customer_id,
                "metodo_pago": payment_method,
                "elementos": [
                    {
                        "producto_id": product_id,
                        "cantidad": quantity,
                        "precio_unitario": unit_price,
                    }
                ],
            },
            headers=headers,
            on_success=self._remember_trace_id,
        )

    def _get_trace(self) -> None:
        """Solicita los spans de un Trace ID especificado o devuelto por la API."""
        trace_id = self.trace_id.get().strip()
        if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
            messagebox.showerror(
                "Trace ID inválido",
                "Ingresa un Trace ID de 32 caracteres hexadecimales en minúsculas.",
                parent=self,
            )
            return
        self._start_request(
            "GET", f"/v1/telemetry/trace/{quote(trace_id, safe='')}"
        )

    def _get_all_spans(self) -> None:
        """Solicita todos los spans guardados en el proceso de la API."""
        self._start_request("GET", "/v1/telemetry/spans")

    @staticmethod
    def _is_valid_traceparent(value: str) -> bool:
        """Comprueba versión 00, campos hexadecimales e IDs distintos de cero."""
        match = TRACEPARENT_PATTERN.fullmatch(value)
        if match is None:
            return False
        trace_id, parent_span_id, _flags = match.groups()
        return any(char != "0" for char in trace_id) and any(
            char != "0" for char in parent_span_id
        )

    def _start_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        on_success: Callable[[Any], None] | None = None,
    ) -> None:
        """Valida la URL base y lanza la solicitud en un hilo de trabajo.

        La llamada de red ocurre fuera del hilo de Tk. Los cambios de widgets
        regresan al hilo principal mediante ``after``.
        """
        base_url = self.api_url.get().strip().rstrip("/")
        try:
            parsed_url = urlsplit(base_url)
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.netloc
                or parsed_url.query
                or parsed_url.fragment
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise ValueError(
                    "Ingresa una URL HTTP(S) válida, sin credenciales, "
                    "parámetros ni fragmento."
                )

            request_headers = {"Accept": "application/json"}
            request_headers.update(headers or {})
            body = None
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            request = Request(
                f"{base_url}{path}",
                data=body,
                headers=request_headers,
                method=method,
            )
        except ValueError as exc:
            messagebox.showerror("Solicitud inválida", str(exc), parent=self)
            return

        self._set_busy(True)
        self.status.set(f"Consultando {path}...")
        threading.Thread(
            target=self._send_request,
            args=(request, path, on_success),
            daemon=True,
        ).start()

    def _send_request(
        self,
        request: Request,
        path: str,
        on_success: Callable[[Any], None] | None,
    ) -> None:
        """Ejecuta HTTP, decodifica el cuerpo y programa la actualización visual."""
        try:
            with urlopen(request, timeout=15) as response:
                result = self._decode_body(response.read())
                status_code = response.status
                response_traceparent = response.headers.get("traceparent")
        except HTTPError as exc:
            # HTTPError incluye contenido útil, como el detalle JSON de un 404.
            result = self._decode_body(exc.read())
            status_code = exc.code
            response_traceparent = exc.headers.get("traceparent")
        except (URLError, TimeoutError, OSError) as exc:
            self.after(0, self._show_error, str(exc))
            return

        self.after(
            0,
            self._show_response,
            status_code,
            result,
            path,
            response_traceparent,
            on_success,
        )

    @staticmethod
    def _decode_body(body: bytes) -> Any:
        """Interpreta el cuerpo como JSON o conserva la respuesta como texto."""
        text = body.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _remember_trace_id(self, result: Any) -> None:
        """Rellena el formulario de consulta con el Trace ID de un pedido."""
        if not isinstance(result, dict):
            return
        telemetry = result.get("telemetria")
        if isinstance(telemetry, dict):
            trace_id = telemetry.get("trace_id")
            if isinstance(trace_id, str):
                self.trace_id.set(trace_id)

    def _show_response(
        self,
        status_code: int,
        result: Any,
        path: str,
        response_traceparent: str | None,
        on_success: Callable[[Any], None] | None,
    ) -> None:
        """Muestra código HTTP, contexto devuelto y cuerpo de la respuesta."""
        self.status.set(f"HTTP {status_code} · {path}")
        formatted_result = (
            json.dumps(result, ensure_ascii=False, indent=2)
            if not isinstance(result, str)
            else result
        )
        if response_traceparent:
            formatted_result = (
                f"traceparent de respuesta: {response_traceparent}\n\n"
                f"{formatted_result}"
            )
        self._write_response(formatted_result)
        if 200 <= status_code < 300 and on_success is not None:
            on_success(result)
        self._set_busy(False)

    def _show_error(self, error: str) -> None:
        """Expone fallas de conexión en la interfaz sin ocultar el error."""
        self.status.set("Error de conexión")
        self._write_response(f"No se pudo completar la solicitud:\n{error}")
        self._set_busy(False)

    def _write_response(self, text: str) -> None:
        """Reemplaza el contenido del panel de resultados de solo lectura."""
        self.response_text.configure(state="normal")
        self.response_text.delete("1.0", "end")
        self.response_text.insert("1.0", text)
        self.response_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        """Desactiva acciones durante una solicitud para evitar duplicados."""
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)


if __name__ == "__main__":
    # Permite ejecutar la aplicación con ``python traceability_client.py``.
    TraceabilityClientApp().mainloop()
