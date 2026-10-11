# Guía: escritorio (GNOME en Wayland)

- **Notificación:** `notify-send -a Ío "Título" "Texto"`.
- **Abrir una web, un archivo o una carpeta** con su programa: `xdg-open URL_O_RUTA`.
- **Abrir una aplicación:** `gtk-launch NOMBRE`, con el nombre del `.desktop` (por ejemplo `org.gnome.Nautilus`, `firefox`, `code`). Para buscar uno: `ls /usr/share/applications ~/.local/share/applications | grep -i NOMBRE`.
- **Volumen:** `wpctl get-volume @DEFAULT_AUDIO_SINK@` y `wpctl set-volume @DEFAULT_AUDIO_SINK@ 50%`.
- **Recordatorio:** `narrador recordar MINUTOS "texto"`. Llega como notificación y en voz alta, aunque Ío esté cerrado. Para anularlo, la orden que imprime (`systemctl --user stop …timer`).
- **Tu voz:** `narrador escucha pausa|activar` y `narrador salida` / `narrador salidas`. El usuario tiene además Super+I para pausar la escucha.
- **Lo que no hay:** portapapeles (falta `wl-clipboard`). En Wayland tampoco se puede traer al frente una ventana de otro programa.
