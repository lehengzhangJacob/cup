import time
import asyncio
import subprocess
from threading import Thread
import numpy as np
import resampy
import soundfile as sf
import edge_tts
from io import BytesIO

from utils.logger import logger
from .base_tts import BaseTTS, State
from registry import register

@register("tts", "edgetts")
class EdgeTTS(BaseTTS):
    def txt_to_audio(self,msg:tuple[str, dict]):
        text,textevent = msg
        voice = self.opt.REF_FILE or "zh-CN-YunxiaNeural" 
        voicename = textevent.get('tts', {}).get('ref_file',voice) #self.opt.REF_FILE #"zh-CN-YunxiaNeural"
        t = time.time()
        process = subprocess.Popen(
            [
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-fflags", "nobuffer", "-f", "mp3", "-i", "pipe:0",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(self.sample_rate), "-ac", "1", "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        stats = {"frames": 0, "first_audio": None}

        def read_pcm():
            chunk_bytes = self.chunk * 2
            pending = bytearray()
            previous = None
            while self.state == State.RUNNING:
                data = process.stdout.read(4096)
                if not data:
                    break
                pending.extend(data)
                while len(pending) >= chunk_bytes:
                    pcm = np.frombuffer(
                        bytes(pending[:chunk_bytes]), dtype="<i2"
                    ).astype(np.float32) / 32768.0
                    del pending[:chunk_bytes]
                    if previous is not None:
                        eventpoint = (
                            {"status": "start", "text": text}
                            if stats["frames"] == 0
                            else {}
                        )
                        eventpoint.update(**textevent)
                        self.parent.put_audio_frame(previous, eventpoint)
                        stats["frames"] += 1
                        if stats["first_audio"] is None:
                            stats["first_audio"] = time.time()
                    previous = pcm
            if previous is not None and self.state == State.RUNNING:
                eventpoint = {"status": "end", "text": text}
                if stats["frames"] == 0:
                    eventpoint["status"] = "start"
                eventpoint.update(**textevent)
                self.parent.put_audio_frame(previous, eventpoint)
                stats["frames"] += 1
                if stats["first_audio"] is None:
                    stats["first_audio"] = time.time()

        reader = Thread(target=read_pcm, daemon=True)
        reader.start()
        try:
            asyncio.new_event_loop().run_until_complete(
                self.__stream_to_ffmpeg(voicename, text, process)
            )
        except Exception:
            logger.exception("edgetts streaming")
        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            reader.join(timeout=10)
            if reader.is_alive() and process.poll() is None:
                process.terminate()
                reader.join(timeout=2)
            if process.poll() is None:
                process.wait(timeout=2)

        first_ms = (
            None
            if stats["first_audio"] is None
            else int((stats["first_audio"] - t) * 1000)
        )
        logger.info(
            "-------edge tts stream total=%.4fs first_audio_ms=%s frames=%s",
            time.time() - t,
            first_ms,
            stats["frames"],
        )

    async def __stream_to_ffmpeg(self, voicename: str, text: str, process):
        communicate = edge_tts.Communicate(text, voicename)
        async for chunk in communicate.stream():
            if self.state != State.RUNNING:
                break
            if chunk["type"] == "audio" and process.stdin:
                try:
                    process.stdin.write(chunk["data"])
                except BrokenPipeError:
                    break

    def __create_bytes_stream(self,byte_stream):
        #byte_stream=BytesIO(buffer)
        stream, sample_rate = sf.read(byte_stream) # [T*sample_rate,] float64
        logger.info(f'[INFO]tts audio stream {sample_rate}: {stream.shape}')
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.info(f'[WARN] audio has {stream.shape[1]} channels, only use the first.')
            stream = stream[:, 0]
    
        if sample_rate != self.sample_rate and stream.shape[0]>0:
            logger.info(f'[WARN] audio sample rate is {sample_rate}, resampling into {self.sample_rate}.')
            stream = resampy.resample(x=stream, sr_orig=sample_rate, sr_new=self.sample_rate)

        return stream
    
    async def __main(self,voicename: str, text: str):
        try:
            communicate = edge_tts.Communicate(text, voicename)

            #with open(OUTPUT_FILE, "wb") as file:
            first = True
            async for chunk in communicate.stream():
                if first:
                    first = False
                if chunk["type"] == "audio" and self.state==State.RUNNING:
                    #self.push_audio(chunk["data"])
                    self.input_stream.write(chunk["data"])
                    #file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    pass
        except Exception as e:
            logger.exception('edgetts')
