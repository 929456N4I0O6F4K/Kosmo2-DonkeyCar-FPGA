# Reference sources and modifications

Sensor reference: Espressif esp32-camera, tag **v2.1.3**.

- sensors/private_include/ov2640_settings.h — retained verbatim, Apache-2.0.
- sensors/private_include/ov2640_regs.h — retained verbatim, original OpenMV MIT notice retained.
- sensors/ov2640.c — retained verbatim for window/clock setup reference.
- LICENSE.esp32-camera — the upstream project license.
- LICENSE.OpenMV — MIT license for the OpenMV register definitions.
- *_source.json — original GitHub contents API responses with git object SHAs and source paths.

Generated/adapted material: rtl/ov2640_init_rom.v and init_manifest.json.

Adaptation in tools/generate_init.py: complete CIF tuning table, CIF sensor window, 400x296 source window scaled to 160x120, RGB565 MSB first, CLKRC=3 (no doubler), fixed DVP divider=8, COM10=0, reset/wait timing, selectable COM7 color bars. The source table is not silently shortened. The SHA256 manifest records the exact retained inputs and numeric output sequence. The actual module oscillator frequency is still unverified.

The FPGA SCCB, capture and packet logic is local implementation. uart_rx.v and uart_tx.v were copied from ../../mypilot/rtl (relative to the camera project root, ../../../mypilot/rtl relative to vendor), with PDS-compatible register preservation in uart_rx.v. The original UART files are unchanged.

