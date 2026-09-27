# CAN Bus Layer: UAV Engine Telemetry (Phase 2)

This layer implements a realistic CAN bus interface for the MALE UAV aero piston powerplant using `python-can` and `cantools`.

---

## 1. CAN Message Matrix (`engine_telemetry.dbc`)

Telemetry is organized into 4 standardized 8-byte frames transmitted at **10 Hz** (total bus throughput ~25.6 kbps, ~10.2% load on a 250 kbps aerospace bus):

| Msg ID | CAN ID (Hex) | Message Name | DLC | Signals Included | Rate |
| :---: | :---: | :--- | :---: | :--- | :---: |
| **256** | `0x100` | `ENGINE_CORE_STATUS` | 8 | `Engine_RPM`, `Throttle_Pct`, `Fuel_Flow_gps`, `Engine_Status_Flags`, `Rolling_Counter`, `Checksum` | 10 Hz |
| **257** | `0x101` | `ENGINE_CYL_EGT` | 8 | `EGT_Cyl1`, `EGT_Cyl2`, `EGT_Cyl3`, `EGT_Cyl4` | 10 Hz |
| **258** | `0x102` | `ENGINE_CYL_CHT` | 8 | `CHT_Cyl1`, `CHT_Cyl2`, `CHT_Cyl3`, `CHT_Cyl4` | 10 Hz |
| **259** | `0x103` | `ENGINE_LUBRICATION_FLIGHT` | 8 | `Oil_Pressure_bar`, `Oil_Temperature_C`, `Airspeed_mps`, `Altitude_m` | 10 Hz |

### Signal Encoding Specifications:
- `Engine_RPM`: 16-bit unsigned, Scale: 0.25, Range: 0 – 8000 RPM
- `Throttle_Pct`: 8-bit unsigned, Scale: 0.5, Range: 0 – 100 %
- `Fuel_Flow_gps`: 16-bit unsigned, Scale: 0.001, Range: 0 – 20.0 g/s
- `EGT_Cyl1..4`: 16-bit unsigned, Scale: 0.1, Range: 0 – 1200 °C
- `CHT_Cyl1..4`: 16-bit unsigned, Scale: 0.1, Range: 0 – 400 °C
- `Oil_Pressure_bar`: 16-bit unsigned, Scale: 0.001, Range: 0 – 10.0 bar
- `Oil_Temperature_C`: 16-bit unsigned, Scale: 0.1, Offset: -40.0, Range: -40 – 200 °C
- `Airspeed_mps`: 16-bit unsigned, Scale: 0.1, Range: 0 – 150 m/s
- `Altitude_m`: 16-bit unsigned, Scale: 0.5, Range: 0 – 10,000 m

---

## 2. Setup Instructions for Virtual CAN (`vcan0`)

### On Linux (Ubuntu / Debian / Raspberry Pi / Mission Computer):
```bash
# 1. Load the Linux Virtual CAN kernel module
sudo modprobe vcan

# 2. Create the virtual CAN network interface
sudo ip link add dev vcan0 type vcan

# 3. Bring the interface up
sudo ip link set up vcan0

# 4. Verify vcan0 is active
ip link show vcan0
```

### On Windows via WSL2:
Standard WSL2 kernels do not compile the `vcan` module by default. To use SocketCAN in WSL2:
1. Build WSL2 kernel with `CONFIG_CAN=m` and `CONFIG_CAN_VCAN=m`.
2. Or use `pip install python-can` directly on native Windows / WSL2 with `bustype='virtual'`.

### On macOS:
The Darwin kernel does not implement Linux SocketCAN. `can_pack.py` and `can_listen.py` **automatically detect macOS** and seamlessly use `python-can`'s built-in memory/virtual bus interface without requiring external kernel drivers.

---

## 3. Running Transceiver & Validation

### Automated Accuracy Test (Round-Trip Verification):
```bash
python3 can_bus/test_can_roundtrip.py
```

### Running Packager (Broadcaster):
```bash
# Broadcast live generated flight profile over CAN
python3 can_bus/can_pack.py --channel vcan0

# Or replay an existing synthetic run CSV from Phase 1
python3 can_bus/can_pack.py --csv data/run_001_injector_clog_cyl2_sev31.csv --realtime
```

### Running Listener (Decoder):
```bash
# In a separate terminal:
python3 can_bus/can_listen.py --channel vcan0 --count 40
```
