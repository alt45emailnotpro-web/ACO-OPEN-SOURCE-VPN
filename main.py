import os
import base64
import threading
import urllib.request

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.clock import Clock

VPNGATE_API_URLS = [
    "https://www.vpngate.net/api/iphone/",
    "http://www.vpngate.net/api/iphone/",
]

CONFIG_DIR_NAME = "ACOVPN"


def get_storage_dir():
    try:
        from android.storage import primary_external_storage_path
        base = primary_external_storage_path()
    except Exception:
        base = os.path.expanduser("~")
    path = os.path.join(base, CONFIG_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def fetch_vpngate_servers():
    last_error = None
    for url in VPNGATE_API_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            servers = {}
            for line in raw.splitlines():
                if line.startswith("*") or line.startswith("#") or not line.strip():
                    continue
                fields = line.split(",")
                if len(fields) < 15:
                    continue
                country = fields[5]
                score = int(fields[2]) if fields[2].isdigit() else 0
                config_b64 = fields[14]
                if not config_b64:
                    continue
                if country not in servers or score > servers[country]["score"]:
                    servers[country] = {"score": score, "config_b64": config_b64, "ip": fields[1]}
            if servers:
                return servers
        except Exception as e:
            last_error = e
    if last_error:
        raise last_error
    return {}


def open_with_ovpn_app(file_path):
    try:
        from jnius import autoclass, cast
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        File = autoclass("java.io.File")
        FileProvider = autoclass("androidx.core.content.FileProvider")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        file_obj = File(file_path)
        authority = activity.getPackageName() + ".fileprovider"
        uri = FileProvider.getUriForFile(activity, authority, file_obj)

        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(uri, "application/x-openvpn-profile")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
        return True, ""
    except Exception as e:
        return False, str(e)


class RootLayout(BoxLayout):
    pass


class AcoVpnAndroidApp(App):
    def build(self):
        self.title = "ACO VPN"
        self.vpngate_servers = {}
        self.storage_dir = get_storage_dir()

        root = BoxLayout(orientation="vertical", padding=16, spacing=10)

        title = Label(text="ACO VPN", font_size=28, size_hint_y=None, height=50, bold=True)
        root.add_widget(title)

        self.status_label = Label(text=f"Config folder: {self.storage_dir}", size_hint_y=None, height=40)
        root.add_widget(self.status_label)

        self.country_spinner = Spinner(text="Tap Refresh List", values=[], size_hint_y=None, height=48)
        root.add_widget(self.country_spinner)

        refresh_btn = Button(text="REFRESH LIST", size_hint_y=None, height=48)
        refresh_btn.bind(on_release=self.refresh_list)
        root.add_widget(refresh_btn)

        download_btn = Button(text="DOWNLOAD SELECTED COUNTRY", size_hint_y=None, height=48)
        download_btn.bind(on_release=self.download_selected)
        root.add_widget(download_btn)

        open_btn = Button(text="OPEN LAST DOWNLOAD IN OPENVPN APP", size_hint_y=None, height=48)
        open_btn.bind(on_release=self.open_last)
        root.add_widget(open_btn)

        self.log_input = TextInput(text="", readonly=True, multiline=True)
        root.add_widget(self.log_input)

        self.last_downloaded_path = None
        self.log("App started.")
        self.log("Needs: OpenVPN for Android (ICS-OpenVPN) installed from Play Store.")
        return root

    def log(self, message):
        self.log_input.text += message + "\n"

    def refresh_list(self, instance):
        self.log("Fetching VPNGate list...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            servers = fetch_vpngate_servers()
            Clock.schedule_once(lambda dt: self._on_list_ready(servers))
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log(f"Error: {e}"))

    def _on_list_ready(self, servers):
        self.vpngate_servers = servers
        countries = sorted(servers.keys())
        self.country_spinner.values = countries
        if countries:
            self.country_spinner.text = countries[0]
        self.log(f"{len(countries)} countries available.")

    def download_selected(self, instance):
        country = self.country_spinner.text
        if country not in self.vpngate_servers:
            self.log("Pick a country from the list first.")
            return
        threading.Thread(target=self._download_worker, args=(country,), daemon=True).start()

    def _download_worker(self, country):
        try:
            entry = self.vpngate_servers[country]
            config_bytes = base64.b64decode(entry["config_b64"])
            safe_name = "".join(ch if ch.isalnum() else "_" for ch in country)
            out_path = os.path.join(self.storage_dir, f"{safe_name}.ovpn")
            with open(out_path, "wb") as f:
                f.write(config_bytes)
            self.last_downloaded_path = out_path
            Clock.schedule_once(lambda dt: self.log(f"Saved: {out_path}"))
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log(f"Error: {e}"))

    def open_last(self, instance):
        if not self.last_downloaded_path:
            self.log("Download a config first.")
            return
        ok, err = open_with_ovpn_app(self.last_downloaded_path)
        if ok:
            self.log("Opened in OpenVPN app.")
        else:
            self.log(f"Could not open automatically: {err}")
            self.log("Open OpenVPN for Android manually and import from: " + self.storage_dir)


if __name__ == "__main__":
    AcoVpnAndroidApp().run()
