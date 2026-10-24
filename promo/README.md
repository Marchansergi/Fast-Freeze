# Vídeo promocional de Fast Freeze

Vídeo de 33 s (1920×1080, 60 fps) generado por código: cada fotograma es la página `index.html`
dibujada en el instante `t`, y la música se sintetiza en `music.py` (sin muestras externas).

```
python music.py music.wav                                   # requiere numpy y scipy
NODE_PATH=$(npm root -g) node render.mjs video video.mp4 60 # requiere Node con Playwright y ffmpeg
ffmpeg -i video.mp4 -i music.wav -c:v copy -c:a aac -b:a 192k -shortest fast-freeze-promo.mp4
```

`node render.mjs stills <carpeta> 1.5 10.4 …` guarda fotogramas sueltos para revisar escenas.
