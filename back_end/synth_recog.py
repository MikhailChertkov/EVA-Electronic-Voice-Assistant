import binascii
import time
import winsound

import pyaudio
import speech_recognition as sr
import json
import sys
import grpc
import os

from back_end import commands, json_reader
from tinkoff_api.tinkoff.cloud.stt.v1 import stt_pb2_grpc, stt_pb2
from tinkoff_api.tinkoff.cloud.tts.v1 import tts_pb2_grpc, tts_pb2
from tinkoff_api.auth import authorization_metadata
from vosk import Model, KaldiRecognizer
from winsound import PlaySound
from PySide2.QtCore import QObject, Signal, QThread


class SynthRecognition(QObject):

    send_text_signal = Signal(str)
    open_api_key = json_reader.get_api()['open_api']
    secret_api_key = json_reader.get_api()['secret_api']
    voice = json_reader.get_voice()
    print(voice)
    model_path = os.path.abspath('../back_end/vosk_small_model_ru')
    print(model_path)
    def __init__(self):
        super().__init__()
        # BACK_END
        self.assistant_name_vars = json_reader.get_assistant_name()
        self.model = Model(self.model_path)
        self.rec = KaldiRecognizer(self.model, 16000)
        self.Commands_obj = commands.Commands()
        # FRONT_END
        self.user_text = ''
        self.close_thread = False

    # Запуск back_end потока
    def run(self):
        self.vosk_speech_recognition()

    # Остановка back_end потока
    def stop(self):
        self.close_thread = True

    # Обновить ключи api
    def update_api(self, open_key, secret_key):
        self.open_api_key = open_key
        self.secret_api_key = secret_key

    # Установить голос
    def set_voice(self, voice):
        self.voice = voice
        return self
        #################################################################################################

    # Получить список голосов (пинг)
    def get_voices_list(self):
        f_name = 'get_voices_list'
        endpoint = os.environ.get("VOICEKIT_ENDPOINT") or "api.tinkoff.ai:443"
        try:
            stub = tts_pb2_grpc.TextToSpeechStub(grpc.secure_channel(endpoint, grpc.ssl_channel_credentials()))
            request = tts_pb2.ListVoicesRequest()
            metadata = authorization_metadata(self.open_api_key, self.secret_api_key, "tinkoff.cloud.tts")
            response = stub.ListVoices(request, metadata=metadata)
            voices = []
            # print(f"[{f_name}] Allowed voices:")
            for voice in sorted(response.voices, key=lambda voice: voice.name):
                # print(f"- {voice.name}")
                voices.append(voice.name)
            print(voices)
            return voices

        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.UNAUTHENTICATED:
                print('v1')
                self.send_text_signal.emit('[v1] Ошибка авторизации. Проверьте API ключи')
                return ['auth error']
            elif rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                print('v2')
                self.send_text_signal.emit('[v2] Отсутствует подключение к сети')
                return ['connection error']
            else:
                print('v3')
                self.send_text_signal.emit('[v3] Произошла внутренняя ошибка')
                return ['unknown error']
        except binascii.Error:
            print('v4')
            self.send_text_signal.emit('[v4] Ошибка авторизации. Проверьте API ключи')
            return ['auth error']
        #################################################################################################

    # Фоновый поиск активационного слова с помощью Vosk
    def vosk_speech_recognition(self):
        f_name = 'vosk_speech_recognition'
        error_happened = False
        while not self.close_thread:
            try:
                # Не обновляется список подключенных устройствё
                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16,
                                channels=1,
                                rate=16000,
                                input=True,
                                frames_per_buffer=8000,
                                input_device_index=1)
                stream.start_stream()
                print('stream vosk started')
                if error_happened:
                    error_happened = False
                    self.send_text_signal.emit('Микрофон успешно подключен')
                    PlaySound('../back_end/audio_beeps/mic_fixed.wav', winsound.SND_FILENAME)
                while not self.close_thread:
                    if self.user_text != '':
                        self.send_text_signal.emit(self.Commands_obj.find_command_fuzz_upd(self.user_text))
                        self.user_text = ''
                    elif self.user_text == '':
                        data = stream.read(4000, exception_on_overflow=False)
                        if self.rec.AcceptWaveform(data) and (len(data)) > 0:
                            ask_name = json.loads(self.rec.Result())
                            if ask_name['text']:
                                print(f'[{f_name}] {ask_name["text"]}')
                                if ask_name['text'] in self.assistant_name_vars:
                                    t_recognized = self.tinkoff_sr_listen_speech_recognition()
                                    if t_recognized is not None:
                                        print(t_recognized)
                                        self.send_text_signal.emit(t_recognized + '#%&')
                                        PlaySound('../back_end/audio_beeps/beep-down.wav', winsound.SND_FILENAME)
                                        answer = self.Commands_obj.find_command_fuzz_upd(t_recognized)
                                        print(answer)
                                        self.send_text_signal.emit(answer)
                                        self.synth_voice(answer)
            except OSError as ose:
                if ose.errno == -9999 or ose.errno == -9998:
                    if not error_happened and ose.errno == -9999:
                        self.send_text_signal.emit('[-9999] Ошибка микрофона. Микрофон отключен. Ассистент работает в режиме чата')
                        PlaySound('../back_end/audio_beeps/error_mic.wav', winsound.SND_FILENAME)
                        print(ose.errno)
                        error_happened = True
                    elif not error_happened and ose.errno == -9998:
                        print(ose.errno)
                        self.send_text_signal.emit('[-9998] Микрофон не найден. Подключите микрофон и перезапустите программу. Ассистент работает в режиме чата. ')
                        PlaySound('../back_end/audio_beeps/error_mic_fatal.wav', winsound.SND_FILENAME)
                        error_happened = True
                    else:
                        if self.user_text != '':
                            self.send_text_signal.emit(self.Commands_obj.find_command_fuzz_upd(self.user_text))
                            self.user_text = ''
                        QThread.msleep(500)
                else:
                    print('some error pyaudio')
            except:
                print('error')
        #################################################################################################

    # Распознавание речи Тинькофф + запись звука с помощью SR_listen
    def tinkoff_sr_listen_speech_recognition(self):
        f_name = 'tinkoff_sr_listen_speech_recognition'
        endpoint = os.environ.get("VOICEKIT_ENDPOINT") or "api.tinkoff.ai:443"

        sample_rate_hertz = 44100
        audio_device_id = 1
        num_channels = 1
        timeout = 3
        phrase_time_limit = 7

        def record():
            r = sr.Recognizer()
            with sr.Microphone(device_index=audio_device_id,
                               sample_rate=sample_rate_hertz) as source:
                PlaySound('../back_end/audio_beeps/beep-up.wav', winsound.SND_FILENAME)
                r.adjust_for_ambient_noise(source, duration=0.5)
                print(f'\n[{f_name}] Energy threshold = {round(r.energy_threshold, 3)}')
                print(f'[{f_name}] listening...')
                st_time = time.time()
                print(f'[{f_name}] Start time', time.time() - st_time)

                try:
                    audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                    print(f'[{f_name}] Finish time', round(time.time() - st_time, 1))
                    print(f'[{f_name}] Size of audio message = '
                          f'{sys.getsizeof(audio.frame_data)} bytes')
                    return tinkoff_request_response(audio)
                except sr.UnknownValueError:
                    print(f'[{f_name}] UnknownValueError')
                    return None
                except sr.WaitTimeoutError:
                    print(f'[{f_name}] WaitTimeoutError')
                    return None

        def tinkoff_request_response(audio):
            try:
                stub = stt_pb2_grpc.SpeechToTextStub(grpc.secure_channel(endpoint, grpc.ssl_channel_credentials()))
                metadata = authorization_metadata(self.open_api_key, self.secret_api_key, "tinkoff.cloud.stt")
                response = stub.Recognize(build_request(audio), metadata=metadata)
                print_recognition_response(response)
                return response.results[0].alternatives[0].transcript.capitalize()

            except grpc.RpcError as rpc_error:
                if rpc_error.code() == grpc.StatusCode.UNAUTHENTICATED:
                    print('r1', self.open_api_key, self.secret_api_key)
                    self.send_text_signal.emit('[r1] Ошибка авторизации. Проверьте API ключи')
                    PlaySound('../back_end/audio_beeps/error_auth.wav', winsound.SND_FILENAME)
                    return None
                elif rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                    print('r2')
                    self.send_text_signal.emit('[r2] Отсутствует подключение к сети')
                    PlaySound('../back_end/audio_beeps/error_connection.wav', winsound.SND_FILENAME)
                    return None
                else:
                    print('r3')
                    self.send_text_signal.emit('[r3] Произошла внутренняя ошибка')
                    PlaySound('../back_end/audio_beeps/error_unknown.wav', winsound.SND_FILENAME)
                    return None
            except binascii.Error:
                print('r4')
                self.send_text_signal.emit('[r4] Ошибка авторизации. Проверьте API ключи')
                PlaySound('../back_end/audio_beeps/error_auth.wav', winsound.SND_FILENAME)
                return None

        def build_request(audio):
            request = stt_pb2.RecognizeRequest()
            request.audio.content = audio.frame_data
            request.config.encoding = stt_pb2.AudioEncoding.LINEAR16
            request.config.sample_rate_hertz = audio.sample_rate
            request.config.num_channels = num_channels
            return request

        def print_recognition_response(response):
            print(f'[{f_name}] {response.results[0].alternatives[0].transcript}')

        return record()
        #################################################################################################

    # Синтез речи
    def synth_voice(self, text):
        f_name = 'synth_voice'
        text = text
        endpoint = os.environ.get("VOICEKIT_ENDPOINT") or "api.tinkoff.ai:443"
        sample_rate = 48000

        def build_request():
            return tts_pb2.SynthesizeSpeechRequest(
                input=tts_pb2.SynthesisInput(
                    text=text
                ),
                audio_config=tts_pb2.AudioConfig(
                    audio_encoding=tts_pb2.LINEAR16,
                    sample_rate_hertz=sample_rate,
                ),
                voice=tts_pb2.VoiceSelectionParams(
                    name=self.voice,
                )
            )
        try:
            pyaudio_lib = pyaudio.PyAudio()
            f = pyaudio_lib.open(output=True, channels=1, format=pyaudio.paInt16, rate=sample_rate)

            stub = tts_pb2_grpc.TextToSpeechStub(grpc.secure_channel(endpoint, grpc.ssl_channel_credentials()))
            request = build_request()
            metadata = authorization_metadata(self.open_api_key, self.secret_api_key, "tinkoff.cloud.tts")
            responses = stub.StreamingSynthesize(request, metadata=metadata)
            for key, value in responses.initial_metadata():
                if key == "x-audio-duration-seconds":
                    print(f'[{f_name}]', "Estimated audio duration is {:.2f} seconds".format(float(value)))
                    break
            for stream_response in responses:
                f.write(stream_response.audio_chunk)
            f.stop_stream()
            f.close()

        except grpc.RpcError as rpc_error:
            if rpc_error.code() == grpc.StatusCode.UNAUTHENTICATED:
                print('s1')
                self.send_text_signal.emit('[s1] Ошибка авторизации. Проверьте API ключи')
                PlaySound('../back_end/audio_beeps/error_auth.wav', winsound.SND_FILENAME)
            elif rpc_error.code() == grpc.StatusCode.UNAVAILABLE:
                print('s2')
                self.send_text_signal.emit('[s2] Отсутствует подключение к сети')
                PlaySound('../back_end/audio_beeps/error_connection.wav', winsound.SND_FILENAME)
            elif rpc_error.code() == grpc.StatusCode.INTERNAL:
                print('s3')
                self.send_text_signal.emit('[s3] Ошибка озвучивания')
                PlaySound('../back_end/audio_beeps/error_voice.wav', winsound.SND_FILENAME)
            else:
                print('s4')
                self.send_text_signal.emit('[s4] Произошла внутренняя ошибка')
                PlaySound('../back_end/audio_beeps/error_unknown.wav', winsound.SND_FILENAME)
        except binascii.Error:
            print('s5')
            self.send_text_signal.emit('[s5] Ошибка авторизации. Проверьте API ключи')
            PlaySound('../back_end/audio_beeps/error_auth.wav', winsound.SND_FILENAME)
        #################################################################################################




if __name__ == '__main__':
    relative_path = os.path.relpath('D:/Mike/Study/8 term/Diplom/Voice_Assistant_Product/back_end/vosk_small_model_ru', 'D:/Mike/Study/8 term/Diplom/Voice_Assistant_Product/user_interface/main.py')

    print(relative_path)