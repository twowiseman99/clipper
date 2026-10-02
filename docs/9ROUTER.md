# Akses 9Router dari CMD

Catatan hasil cek langsung di box `43.157.203.118`, bukan tebakan.

## Kondisi sekarang

| Hal | Nilai |
|---|---|
| Service | `9router.service` — **active (running)** |
| Proses | `/usr/bin/node /usr/lib/node_modules/9router/app/custom-server.js` |
| Listen | `127.0.0.1:20128` dan `[::1]:20128` |
| Base URL | `http://localhost:20128/v1` |
| Model aktif Clipper | `cc/claude-sonnet-5` |
| Jumlah model | 26 |

**Yang paling penting:** 9Router listen di **127.0.0.1 doang**, bukan `0.0.0.0`.
Artinya dari laptop lu, `http://43.157.203.118:20128` **TIDAK akan bisa** —
bukan firewall, tapi emang sengaja ga dibuka keluar. Harus lewat SSH tunnel.

Di box ini sendiri udah ada tunnel jalan:
`ssh -L 20128:127.0.0.1:20128 ubuntu@43.157.203.118`

---

## Cara akses dari CMD Windows

### 1. Buka tunnel (biarkan jendela ini kebuka)

```cmd
ssh -L 20128:127.0.0.1:20128 ubuntu@43.157.203.118
```

Masukin password box. Selama jendela CMD ini kebuka, `localhost:20128` di
laptop lu nyambung ke 9Router di box.

Mau tunnel doang tanpa shell (langsung ke background):

```cmd
ssh -N -f -L 20128:127.0.0.1:20128 ubuntu@43.157.203.118
```

Kalau port 20128 udah kepake di laptop, pakai port lain di sisi kiri:

```cmd
ssh -L 29000:127.0.0.1:20128 ubuntu@43.157.203.118
```

Nanti base URL-nya jadi `http://localhost:29000/v1`.

### 2. Set API key di CMD baru

Sesi ini aja:
```cmd
set NINEROUTER_API_KEY=<key-lu>
```

Permanen (buka CMD baru setelah ini):
```cmd
setx NINEROUTER_API_KEY "<key-lu>"
```

Key-nya ada di `/home/ubuntu/clipper/.env` baris `NINEROUTER_API_KEY=`.

### 3. Tes koneksi

```cmd
curl http://localhost:20128/v1/models -H "Authorization: Bearer %NINEROUTER_API_KEY%"
```

Kalau balik JSON isi daftar model → **tunnel jalan**.
Kalau `Connection refused` → tunnel-nya mati atau belum kebuka.

### 4. Tes chat beneran

```cmd
curl http://localhost:20128/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer %NINEROUTER_API_KEY%" -d "{\"model\":\"cc/claude-sonnet-5\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"halo\"}]}"
```

**`"stream": false` itu wajib.** 9Router default-nya balikin SSE
(`data: {...}` beruntun), dan itu bikin parser JSON biasa pecah. Ini persis
bug yang dulu bikin `ai.py` error — jangan diulang.

Escape kutip di CMD emang jelek. Kalau ribet, pakai PowerShell:

```powershell
$body = @{
  model = "cc/claude-sonnet-5"
  stream = $false
  messages = @(@{ role = "user"; content = "halo" })
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:20128/v1/chat/completions" `
  -Method Post -ContentType "application/json" `
  -Headers @{ Authorization = "Bearer $env:NINEROUTER_API_KEY" } `
  -Body $body
```

---

## Daftar model (26)

API-nya OpenAI-compatible, jadi tinggal ganti base URL + model.

**Claude (`cc/`) — dipakai Clipper sekarang**
```
cc/claude-opus-5
cc/claude-sonnet-5           <-- default Clipper
cc/claude-fable-5-1
cc/claude-fable-5
cc/claude-haiku-4-5-20251001
```

**Gemini (`ag/`)**
```
ag/gemini-3.8-flash-high / -medium / -low / (plain)
ag/gemini-3.7-flash-high / -medium / -low
ag/gemini-3.6-flash-high / -medium / -low
ag/gemini-3.5-flash-high / -low / -extra-low
ag/gemini-3-flash / -flash-agent
ag/gemini-pro-agent
ag/gemini-3.1-pro-low
```

**Lainnya**
```
ag/claude-sonnet-4-6
ag/claude-opus-4-6-thinking
ag/gpt-oss-120b-medium
combo1                        <-- alias combo, dipakai Hermes
```

Soal `combo1`: itu alias yang nge-route ke model lain di belakang. Enak buat
dipakai harian, tapi kalau lu lagi debug sesuatu, pakai nama model spesifik —
biar jelas siapa yang jawab.

---

## Pakai di tool lain

**Python (OpenAI SDK)**
```python
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:20128/v1",
    api_key="<key-lu>",
)
r = client.chat.completions.create(
    model="cc/claude-sonnet-5",
    messages=[{"role": "user", "content": "halo"}],
    stream=False,
)
print(r.choices[0].message.content)
```

**Cursor / Continue / aplikasi OpenAI-compatible lain**
- Base URL: `http://localhost:20128/v1`
- API Key: key dari `.env`
- Model: `cc/claude-sonnet-5`

**Ganti model Clipper** — edit `/home/ubuntu/clipper/.env`:
```
NINEROUTER_MODEL=cc/claude-opus-5
```
`job.py` manggil `_load_dotenv()` di awal, jadi ga usah restart apa-apa.

---

## Kalau ngadat

**`Connection refused` dari laptop**
Tunnel mati. Cek jendela CMD yang jalanin `ssh -L` masih kebuka apa engga.
Kalau pakai `-f`, cek: `tasklist | findstr ssh`

**`Connection refused` di box sendiri**
```bash
systemctl status 9router
sudo systemctl restart 9router
```

**JSONDecodeError / output aneh `data: {...}`**
`"stream": false` kelupaan. Ini penyebab paling sering.

**401 / Unauthorized**
Key salah atau `%NINEROUTER_API_KEY%` kosong. Cek: `echo %NINEROUTER_API_KEY%`

**429 / rate limit**
Kena limit upstream, bukan salah config. Tunggu bentar. `ai.py` udah ada
retry + backoff (`NINEROUTER_RETRIES`, `NINEROUTER_BACKOFF`).

**Model ga ketemu**
Nama model harus persis, termasuk prefix `cc/` atau `ag/`. Cek dulu lewat
`/v1/models`.

---

## Kenapa ga dibuka ke publik aja

Sempat kepikiran nyaranin `0.0.0.0` biar ga usah tunnel — **jangan**.
9Router ga punya rate-limit per-IP dan key-nya sekali bocor bisa dipakai
siapa aja buat bakar kuota lu. SSH tunnel cuma nambah satu langkah dan
jauh lebih aman.
