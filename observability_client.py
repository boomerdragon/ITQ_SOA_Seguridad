"""Cliente gráfico Tkinter para la API de ``observability_main.py``.

La ventana permite consultar los health checks y las métricas, enviar una
solicitud de negocio ficticia y cambiar el estado simulado de la base de datos.
No requiere paquetes externos: usa ``urllib`` de la biblioteca estándar.

Ejecuta primero la API desde la carpeta del proyecto:
    uvicorn observability_main:app --reload

Después inicia este cliente:
    python observability_client.py
"""

import json
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import messagebox, ttk


class ObservabilityClientApp(tk.Tk):
    """Interfaz para explorar los endpoints de observabilidad y negocio."""

    def __init__(self) -> None:
        """Configura la ventana, los valores iniciales y construye la interfaz."""
        super().__init__()
        self.title("Cliente de Observabilidad SOA")
        # La geometría inicial corresponde a la resolución indicada por el usuario.
        self.geometry("1366x768")
        self.minsize(1100, 650)

        self.api_url = tk.StringVar(value="http://127.0.0.1:8000")
        self.cliente_id = tk.StringVar(value="CLI-9941")
        self.servicio_tipo = tk.StringVar(value="CONSULTA_SALDO")
        self.prioridad = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Listo")
        self.action_buttons: list[ttk.Button] = []

        self._build_ui()

    def _build_ui(self) -> None:
        """Distribuye las acciones, el formulario y los paneles de resultados."""
        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        ttk.Label(
            container,
            text="Panel de observabilidad",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # La URL base se puede cambiar para apuntar a otra instancia de la API.
        api_frame = ttk.Frame(container)
        api_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        api_frame.columnconfigure(1, weight=1)
        ttk.Label(api_frame, text="URL base de la API").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ttk.Entry(api_frame, textvariable=self.api_url).grid(
            row=0, column=1, sticky="ew"
        )

        # Estos botones consultan las comprobaciones y la exportación de métricas.
        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self._add_action_button(
            actions, "Comprobar liveness", self._check_liveness
        ).pack(side="left")
        self._add_action_button(
            actions, "Comprobar readiness", self._check_readiness
        ).pack(side="left", padx=(8, 0))
        self._add_action_button(
            actions, "Actualizar métricas", self._get_metrics
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            actions,
            text="Liveness confirma que el proceso responde; readiness "
            "comprueba las dependencias simuladas.",
        ).pack(side="left", padx=(18, 0))

        content = ttk.Frame(container)
        content.grid(row=3, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1, uniform="panels")
        content.columnconfigure(1, weight=1, uniform="panels")
        content.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(content)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        left_panel.columnconfigure(0, weight=1)
        right_panel = ttk.Frame(content)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)
        right_panel.rowconfigure(2, weight=1)

        self._build_service_form(left_panel)
        self._build_dependency_controls(left_panel)
        self._build_metrics_panel(right_panel)
        self._build_response_panel(right_panel)

        ttk.Separator(container).grid(row=4, column=0, sticky="ew", pady=(8, 5))
        ttk.Label(container, textvariable=self.status).grid(
            row=5, column=0, sticky="w"
        )

    def _add_action_button(
        self, parent: ttk.Widget, text: str, command: Callable[[], None]
    ) -> ttk.Button:
        """Crea un botón de acción y lo registra para bloquearlo durante HTTP."""
        button = ttk.Button(parent, text=text, command=command)
        self.action_buttons.append(button)
        return button

    def _build_service_form(self, parent: ttk.Frame) -> None:
        """Crea el formulario para ``POST /v1/servicios/procesar``."""
        frame = ttk.LabelFrame(
            parent, text="Procesar servicio de negocio (simulado)", padding=14
        )
        frame.grid(row=0, column=0, sticky="new", pady=(0, 12))
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text=(
                "La API simula una latencia y puede generar un error aleatorio. "
                "No ejecuta una transacción real."
            ),
            wraplength=560,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        fields = (
            ("ID del cliente", self.cliente_id),
            ("Tipo de servicio", self.servicio_tipo),
            ("Prioridad (1 a 5)", self.prioridad),
        )
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5
            )
            ttk.Entry(frame, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=5
            )

        self._add_action_button(
            frame, "Enviar solicitud", self._submit_service
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

    def _build_dependency_controls(self, parent: ttk.Frame) -> None:
        """Crea acciones para simular una caída o recuperación de la base de datos."""
        frame = ttk.LabelFrame(
            parent, text="Dependencia: base de datos", padding=14
        )
        frame.grid(row=1, column=0, sticky="new")
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text=(
                "Usa estos controles para probar readiness. Al simular una "
                "caída, el health check debe responder HTTP 503; después "
                "restablece la conexión para recuperar HTTP 200."
            ),
            wraplength=560,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self._add_action_button(
            frame, "Simular caída de DB", self._simulate_database_failure
        ).grid(row=1, column=0, sticky="w")
        self._add_action_button(
            frame, "Restablecer DB", self._restore_database
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))

        ttk.Label(
            parent,
            text=(
                "Endpoints usados: GET /health/liveness, "
                "GET /health/readiness, GET /metrics, "
                "POST /v1/servicios/procesar y POST /admin/simular-falla-db."
            ),
            wraplength=580,
        ).grid(row=2, column=0, sticky="w", pady=(14, 0))

    def _build_metrics_panel(self, parent: ttk.Frame) -> None:
        """Prepara el panel que muestra el texto exportado en formato Prometheus."""
        frame = ttk.LabelFrame(parent, text="Métricas Prometheus", padding=8)
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.metrics_text = tk.Text(
            frame, wrap="none", height=12, state="disabled", font=("Consolas", 10)
        )
        vertical_scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.metrics_text.yview
        )
        horizontal_scrollbar = ttk.Scrollbar(
            frame, orient="horizontal", command=self.metrics_text.xview
        )
        self.metrics_text.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        self.metrics_text.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self._write_text(self.metrics_text, "Presiona «Actualizar métricas» para consultar /metrics.")

    def _build_response_panel(self, parent: ttk.Frame) -> None:
        """Prepara el panel para mostrar el código HTTP y la respuesta más reciente."""
        frame = ttk.LabelFrame(parent, text="Respuesta de la API", padding=8)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.response_text = tk.Text(
            frame, wrap="word", height=10, state="disabled"
        )
        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.response_text.yview
        )
        self.response_text.configure(yscrollcommand=scrollbar.set)
        self.response_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._write_text(
            self.response_text,
            "Aquí aparecerán el código HTTP y el cuerpo de cada respuesta.",
        )

    def _check_liveness(self) -> None:
        """Consulta el endpoint que confirma que el proceso de la API está activo."""
        self._start_request("GET", "/health/liveness")

    def _check_readiness(self) -> None:
        """Consulta el estado de disponibilidad de las dependencias simuladas."""
        self._start_request("GET", "/health/readiness")

    def _get_metrics(self) -> None:
        """Solicita las métricas y las presenta tanto en la respuesta como en su panel."""
        self._start_request(
            "GET", "/metrics", on_success=self._update_metrics
        )

    def _submit_service(self) -> None:
        """Valida localmente el formulario y envía la solicitud de negocio."""
        client_id = self.cliente_id.get().strip()
        service_type = self.servicio_tipo.get().strip()
        try:
            priority = int(self.prioridad.get())
            if not 1 <= priority <= 5:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Prioridad inválida",
                "Ingresa un número entero de prioridad entre 1 y 5.",
                parent=self,
            )
            return

        if not client_id or not service_type:
            messagebox.showerror(
                "Datos incompletos",
                "Ingresa el ID del cliente y el tipo de servicio.",
                parent=self,
            )
            return

        self._start_request(
            "POST",
            "/v1/servicios/procesar",
            payload={
                "cliente_id": client_id,
                "servicio_tipo": service_type,
                "prioridad": priority,
            },
        )

    def _simulate_database_failure(self) -> None:
        """Marca inactiva la DB simulada mediante el endpoint administrativo."""
        self._start_request("POST", "/admin/simular-falla-db?activa=false")

    def _restore_database(self) -> None:
        """Restaura la DB simulada para que readiness vuelva a estar disponible."""
        self._start_request("POST", "/admin/simular-falla-db?activa=true")

    def _start_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        on_success: Callable[[Any], None] | None = None,
    ) -> None:
        """Valida y crea la solicitud, que se ejecuta en un hilo de trabajo.

        Tkinter no debe bloquearse mientras se espera la red. Por eso el hilo
        secundario hace la llamada y programa las actualizaciones visuales con
        ``after``, que ejecuta los cambios de widgets en el hilo de la interfaz.
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
                    "Ingresa una URL base HTTP(S) válida, sin credenciales, "
                    "parámetros ni fragmento."
                )

            headers = {"Accept": "application/json, text/plain"}
            body = None
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = Request(
                f"{base_url}{path}",
                data=body,
                headers=headers,
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
        """Realiza HTTP y devuelve respuestas exitosas o de error a Tkinter."""
        try:
            with urlopen(request, timeout=15) as response:
                result = self._decode_body(response.read())
                status_code = response.status
        except HTTPError as exc:
            # HTTPError también contiene una respuesta útil, por ejemplo el JSON 503.
            result = self._decode_body(exc.read())
            status_code = exc.code
        except (URLError, TimeoutError, OSError) as exc:
            self.after(0, self._show_error, str(exc))
            return

        self.after(
            0, self._show_response, status_code, result, path, on_success
        )

    @staticmethod
    def _decode_body(body: bytes) -> Any:
        """Convierte una respuesta JSON a objetos Python o conserva su texto."""
        text = body.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _update_metrics(self, result: Any) -> None:
        """Actualiza el panel Prometheus si el cuerpo recibido es texto."""
        if isinstance(result, str):
            self._write_text(self.metrics_text, result)

    def _show_response(
        self,
        status_code: int,
        result: Any,
        path: str,
        on_success: Callable[[Any], None] | None,
    ) -> None:
        """Muestra el estado HTTP y el resultado; procesa callbacks exitosos."""
        self.status.set(f"HTTP {status_code} — {path}")
        formatted_result = (
            json.dumps(result, ensure_ascii=False, indent=2)
            if not isinstance(result, str)
            else result
        )
        self._write_text(self.response_text, formatted_result)
        if 200 <= status_code < 300 and on_success is not None:
            on_success(result)
        self._set_busy(False)

    def _show_error(self, error: str) -> None:
        """Expone fallas de conexión en la interfaz sin ocultar el error."""
        self.status.set("Error de conexión")
        self._write_text(
            self.response_text, f"No se pudo completar la solicitud:\n{error}"
        )
        self._set_busy(False)

    @staticmethod
    def _write_text(widget: tk.Text, text: str) -> None:
        """Reemplaza el contenido de un widget de texto de solo lectura."""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        """Bloquea acciones mientras hay una solicitud para evitar duplicados."""
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)


if __name__ == "__main__":
    # Este bloque permite abrir la aplicación directamente con Python.
    ObservabilityClientApp().mainloop()
