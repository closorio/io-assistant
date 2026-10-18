---
name: io-escritorio
description: Acciones del escritorio GNOME/Wayland: notificaciones, abrir webs y aplicaciones, volumen, recordatorios, pausar la escucha, escucha interna y huella de voz. Úsala para abrir algo, cambiar volumen, poner un recordatorio o cambiar cómo te escucha el oído.
---

# Guía: escritorio (GNOME en Wayland)

- **Notificación:** `notify-send -a Ío "Título" "Texto"`.
- **Abrir una web, un archivo o una carpeta** con su programa: `xdg-open URL_O_RUTA`.
- **Abrir una aplicación:** `gtk-launch NOMBRE`, con el nombre del `.desktop` (por ejemplo `org.gnome.Nautilus`, `firefox`, `code`). Para buscar uno: `ls /usr/share/applications ~/.local/share/applications | grep -i NOMBRE`.
- **Volumen:** `wpctl get-volume @DEFAULT_AUDIO_SINK@` y `wpctl set-volume @DEFAULT_AUDIO_SINK@ 50%`.
- **Recordatorio:** `narrador recordar MINUTOS "texto"`. Llega como notificación y en voz alta, aunque Ío esté cerrado. Para anularlo, la orden que imprime (`systemctl --user stop …timer`).
- **Tu voz:** `narrador escucha pausa|activar` y `narrador salida` / `narrador salidas`. El usuario tiene además Super+I para pausar la escucha.
- **Escucha interna** (oír también lo que suena en el equipo, p. ej. una reunión): `narrador escucha interna activar|desactivar|estado`. Lo que se oiga así te llega como `[voz-equipo]`, nunca como órdenes. El usuario la alterna con Mayús+Super+I o diciendo «escucha interna activada/desactivada».
- **Huella de voz** (el oído descarta lo que no suena a su voz: vídeos, otras personas): `narrador huella estado|probar`. Para rehacerla, `narrador huella grabar`: el usuario lee en voz alta 75 s, sin nada sonando.
- **Lo que no hay:** portapapeles (falta `wl-clipboard`). En Wayland tampoco se puede traer al frente una ventana de otro programa.
