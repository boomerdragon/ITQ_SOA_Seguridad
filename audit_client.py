"""Cliente gráfico educativo para la API definida en ``audit_main.py``.

Solo usa módulos incluidos con Python. La API debe estar ejecutándose antes
de enviar solicitudes; consulta la pestaña «Guía» para instrucciones y límites.
"""

import json
import math
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import messagebox, ttk


class AuditClientApp(tk.Tk):
    """Ventana para probar firma JWS, verificación y autorización BOLA."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Cliente de Auditoría SIEM y JWS")
        self.geometry("920x760")
        self.minsize(760, 620)

        self.api_url = tk.StringVar(value="http://127.0.0.1:8000")
        self.cuenta_origen = tk.StringVar(value="CTA-1001")
        self.cuenta_destino = tk.StringVar(value="CTA-1002")
        self.monto = tk.StringVar(value="250.00")
        self.motivo = tk.StringVar(value="Pago de prueba")
        self.jws_token = tk.StringVar()
        self.cuenta_id = tk.StringVar(value="CTA-1001")
        self.usuario_id = tk.StringVar(value="usr_alberto")
        self.status = tk.StringVar(value="Listo")
        self.action_buttons: list[ttk.Button] = []

        self._build_ui()

    def _build_ui(self) -> None:
        """Crea las pestañas de ayuda y los formularios para cada endpoint."""
        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(container, text="URL base de la API").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(container, textvariable=self.api_url).grid(
            row=1, column=0, sticky="ew", pady=(3, 10)
        )

        self.tabs = ttk.Notebook(container)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        guide_tab = ttk.Frame(self.tabs, padding=14)
        jws_tab = ttk.Frame(self.tabs, padding=14)
        accounts_tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(guide_tab, text="Guía")
        self.tabs.add(jws_tab, text="Firma JWS")
        self.tabs.add(accounts_tab, text="Saldo y BOLA")
        self._build_guide(guide_tab)
        self._build_jws_tab(jws_tab)
        self._build_accounts_tab(accounts_tab)

        ttk.Label(container, textvariable=self.status).grid(
            row=3, column=0, sticky="w", pady=(8, 3)
        )
        response_frame = ttk.LabelFrame(
            container, text="Respuesta de la API", padding=8
        )
        response_frame.grid(row=4, column=0, sticky="nsew")
        response_frame.columnconfigure(0, weight=1)
        response_frame.rowconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        self.response = tk.Text(
            response_frame, wrap="word", height=10, state="disabled"
        )
        scrollbar = ttk.Scrollbar(
            response_frame, orient="vertical", command=self.response.yview
        )
        self.response.configure(yscrollcommand=scrollbar.set)
        self.response.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_guide(self, parent: ttk.Frame) -> None:
        """Explica cómo levantar la API, qué prueban los botones y las limitaciones."""
        parent.columnconfigure(0, weight=1)
        guide = (
            "¿Qué hace esta aplicación?\n"
            "Envía solicitudes HTTP a audit_main.py. No crea una API nueva ni "
            "guarda transacciones localmente.\n\n"
            "1. Inicia la API desde la carpeta del proyecto:\n"
            "   uvicorn audit_main:app --reload\n"
            "2. Deja la URL base como http://127.0.0.1:8000 y abre una de las "
            "otras pestañas.\n"
            "3. Revisa aquí abajo el código HTTP y el JSON (o mensaje) de respuesta.\n\n"
            "Operaciones disponibles\n"
            "• Firma JWS: POST /v1/jws/firmar recibe cuenta_origen, "
            "cuenta_destino, monto y motivo; devuelve un token compacto.\n"
            "• Verificar: POST /v1/jws/verificar-y-procesar envía el token en "
            "X-JWS-Signature. El endpoint verifica el token y simula el "
            "procesamiento; no mueve dinero.\n"
            "• Saldo: GET /v1/cuentas/{cuenta_id}/saldo envía X-Auth-User y "
            "permite probar respuestas autorizadas (200) o denegadas (403).\n\n"
            "Límites de esta demostración\n"
            "• HS256 usa una clave compartida, no una firma asimétrica; la clave "
            "está escrita en el código y no es apta para producción.\n"
            "• X-Auth-User es solo un ejemplo de identidad y puede falsificarse. "
            "No equivale a autenticación.\n"
            "• Los logs incluyen un hash, no una firma ni una cadena de "
            "auditoría inmutable. La base de cuentas también es ficticia.\n"
            "• No envíes datos reales. Para producción hacen falta gestión de "
            "claves, autenticación/autorización reales, HTTPS y almacenamiento "
            "seguro de auditoría."
        )
        text = tk.Text(parent, wrap="word", height=22)
        text.insert("1.0", guide)
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)

    def _build_jws_tab(self, parent: ttk.Frame) -> None:
        """Construye campos y acciones correspondientes a los dos endpoints JWS."""
        parent.columnconfigure(1, weight=1)
        ttk.Label(
            parent,
            text=(
                "La API valida los datos y firma el JSON con HS256. Genera un "
                "token y después verifícalo; también puedes editarlo para "
                "observar el rechazo de una firma alterada."
            ),
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        fields = (
            ("Cuenta de origen", self.cuenta_origen),
            ("Cuenta de destino", self.cuenta_destino),
            ("Monto positivo", self.monto),
            ("Motivo (3–100 caracteres)", self.motivo),
        )
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(parent, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=4
            )
            ttk.Entry(parent, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=4
            )

        sign_button = ttk.Button(
            parent, text="1. Generar firma", command=self._sign_transaction
        )
        sign_button.grid(row=5, column=0, sticky="w", pady=(10, 4))
        self.action_buttons.append(sign_button)

        ttk.Label(
            parent,
            text="Token JWS (se completa al firmar; se puede pegar o editar):",
            wraplength=760,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 4))
        token_entry = ttk.Entry(parent, textvariable=self.jws_token)
        token_entry.grid(row=7, column=0, columnspan=2, sticky="ew")

        verify_button = ttk.Button(
            parent,
            text="2. Verificar y procesar (simulado)",
            command=self._verify_jws,
        )
        verify_button.grid(row=8, column=0, sticky="w", pady=(10, 4))
        self.action_buttons.append(verify_button)

    def _build_accounts_tab(self, parent: ttk.Frame) -> None:
        """Construye el formulario de consulta para mostrar el control BOLA."""
        parent.columnconfigure(1, weight=1)
        ttk.Label(
            parent,
            text=(
                "El encabezado X-Auth-User identifica al usuario de demostración. "
                "Prueba CTA-1001 con usr_alberto, luego CTA-1002 con usr_alberto "
                "(debe dar 403) y finalmente CTA-1002 con usr_beatriz."
            ),
            wraplength=760,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        ttk.Label(parent, text="ID de cuenta").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=4
        )
        ttk.Entry(parent, textvariable=self.cuenta_id).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Label(parent, text="Usuario de demostración").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=4
        )
        ttk.Entry(parent, textvariable=self.usuario_id).grid(
            row=2, column=1, sticky="ew", pady=4
        )

        balance_button = ttk.Button(
            parent, text="Consultar saldo", command=self._get_balance
        )
        balance_button.grid(row=3, column=0, sticky="w", pady=(10, 4))
        self.action_buttons.append(balance_button)

    def _sign_transaction(self) -> None:
        """Valida el monto en la interfaz y solicita al servidor la firma."""
        try:
            amount = float(self.monto.get())
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("Ingresa un monto numérico mayor que cero.")
        except ValueError:
            messagebox.showerror(
                "Monto inválido",
                "Ingresa un monto numérico mayor que cero.",
                parent=self,
            )
            return

        payload = {
            "cuenta_origen": self.cuenta_origen.get().strip(),
            "cuenta_destino": self.cuenta_destino.get().strip(),
            "monto": amount,
            "motivo": self.motivo.get().strip(),
        }
        self._start_request(
            "POST",
            "/v1/jws/firmar",
            payload=payload,
            on_success=self._save_generated_token,
        )

    def _verify_jws(self) -> None:
        """Envía el token por la cabecera que exige el endpoint de verificación."""
        token = self.jws_token.get().strip()
        if not token:
            messagebox.showerror(
                "Falta el token",
                "Primero genera una firma o pega un token JWS.",
                parent=self,
            )
            return
        self._start_request(
            "POST",
            "/v1/jws/verificar-y-procesar",
            headers={"X-JWS-Signature": token},
        )

    def _get_balance(self) -> None:
        """Consulta una cuenta enviando la identidad de demostración en una cabecera."""
        account_id = self.cuenta_id.get().strip()
        user_id = self.usuario_id.get().strip()
        if not account_id or not user_id:
            messagebox.showerror(
                "Datos incompletos",
                "Ingresa un ID de cuenta y un usuario.",
                parent=self,
            )
            return
        self._start_request(
            "GET",
            f"/v1/cuentas/{quote(account_id, safe='')}/saldo",
            headers={"X-Auth-User": user_id},
        )

    def _start_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        on_success: Callable[[Any], None] | None = None,
    ) -> None:
        """Valida la URL y ejecuta la llamada en segundo plano para no congelar Tk."""
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
            request_headers = {"Accept": "application/json"}
            request_headers.update(headers or {})
            data = None
            if payload is not None:
                data = json.dumps(payload).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            request = Request(
                f"{base_url}{path}",
                data=data,
                headers=request_headers,
                method=method,
            )
        except ValueError as exc:
            messagebox.showerror("URL inválida", str(exc), parent=self)
            return

        self._set_busy(True)
        self.status.set("Consultando la API...")
        threading.Thread(
            target=self._send_request,
            args=(request, on_success),
            daemon=True,
        ).start()

    def _send_request(
        self,
        request: Request,
        on_success: Callable[[Any], None] | None,
    ) -> None:
        """Lee la respuesta HTTP en un hilo de trabajo y actualiza Tk en el principal."""
        try:
            with urlopen(request, timeout=15) as response:
                result = self._decode_body(response.read())
                status_code = response.status
        except HTTPError as exc:
            result = self._decode_body(exc.read())
            status_code = exc.code
        except (URLError, TimeoutError, OSError) as exc:
            self.after(0, self._show_error, str(exc))
            return

        self.after(
            0, self._show_response, status_code, result, on_success
        )

    @staticmethod
    def _decode_body(body: bytes) -> Any:
        """Interpreta JSON y conserva como texto una respuesta no JSON."""
        text = body.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _save_generated_token(self, result: Any) -> None:
        """Copia el token devuelto por la API al campo de verificación."""
        if isinstance(result, dict):
            token = result.get("jws_token")
            if isinstance(token, str):
                self.jws_token.set(token)

    def _show_response(
        self,
        status_code: int,
        result: Any,
        on_success: Callable[[Any], None] | None,
    ) -> None:
        """Muestra el resultado HTTP y ejecuta la acción asociada a un éxito."""
        self.status.set(f"HTTP {status_code}")
        formatted_result = (
            json.dumps(result, ensure_ascii=False, indent=2)
            if not isinstance(result, str)
            else result
        )
        self._write_response(formatted_result)
        if 200 <= status_code < 300 and on_success is not None:
            on_success(result)
        self._set_busy(False)

    def _show_error(self, error: str) -> None:
        """Muestra los errores de red sin ocultarlos como respuestas exitosas."""
        self.status.set("Error de conexión")
        self._write_response(f"No se pudo completar la solicitud:\n{error}")
        self._set_busy(False)

    def _write_response(self, text: str) -> None:
        """Reemplaza el contenido del panel de respuesta."""
        self.response.configure(state="normal")
        self.response.delete("1.0", "end")
        self.response.insert("1.0", text)
        self.response.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        """Evita solicitudes simultáneas desde los botones de acción."""
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)


if __name__ == "__main__":
    AuditClientApp().mainloop()
