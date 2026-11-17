import React, {useEffect, useRef, useState} from 'react';
import {Room, RoomEvent, Track} from 'livekit-client';

export default function LessonCall({lessonId, onClose}) {
 const media = useRef(null);
 const session = useRef(null);
 const [room, setRoom] = useState(null);
 const [status, setStatus] = useState('Подключаемся…');
 const [microphone, setMicrophone] = useState(false);
 const [camera, setCamera] = useState(false);
 const [busy, setBusy] = useState(false);
 const [audioBlocked, setAudioBlocked] = useState(false);

 useEffect(() => {
  let closed = false;
  const request = new AbortController();
  const connection = new Room();
  session.current = connection;
  const attach = track => {
   if (!closed && media.current) media.current.append(track.attach());
  };
  const detach = track => track.detach().forEach(element => element.remove());
  connection.on(RoomEvent.TrackSubscribed, attach)
   .on(RoomEvent.TrackUnsubscribed, detach)
   .on(RoomEvent.LocalTrackPublished, publication => {
    if (!closed && media.current && publication.source === Track.Source.Camera && publication.track) {
     const preview = publication.track.attach();
     preview.dataset.localCamera = 'true';
     media.current.append(preview);
    }
   })
   .on(RoomEvent.LocalTrackUnpublished, publication => {
    if (publication.track) detach(publication.track);
    media.current?.querySelectorAll('video').forEach(element => {
     if (element.dataset.localCamera) element.remove();
    });
   })
   .on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (!closed) setAudioBlocked(!connection.canPlaybackAudio);
   })
   .on(RoomEvent.Reconnecting, () => { if (!closed) setStatus('Восстанавливаем связь…'); })
   .on(RoomEvent.Reconnected, () => { if (!closed) setStatus('Подключено'); })
   .on(RoomEvent.Disconnected, () => {
    if (!closed) {
     setRoom(null);
     setStatus('Звонок завершён. Закройте панель, чтобы подключиться снова.');
    }
   });

  async function connect() {
   try {
    const response = await fetch('/api/lessons/' + lessonId + '/call/token', {
     method: 'POST', headers: {'X-Requested-With': 'KrugPi'}, signal: request.signal,
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Не удалось подключиться');
    if (closed) return;
    await connection.connect(data.url, data.token);
    if (closed) {
     await connection.disconnect();
     return;
    }
    setRoom(connection);
    setStatus('Подключено. Включите микрофон, чтобы начать разговор.');
   } catch (error) {
    if (!closed) setStatus(error.message || 'Видеосвязь недоступна');
   }
  }
  void connect();
  return () => {
   closed = true;
   request.abort();
   session.current = null;
   void connection.disconnect();
  };
 }, [lessonId]);

 async function toggle(kind) {
  setBusy(true);
  try {
   if (kind === 'microphone') {
    await room.localParticipant.setMicrophoneEnabled(!microphone);
    if (session.current === room) setMicrophone(!microphone);
   } else {
    await room.localParticipant.setCameraEnabled(!camera);
    if (session.current === room) setCamera(!camera);
   }
   if (session.current === room) setStatus('Подключено');
  } catch {
   if (session.current === room) setStatus('Проверьте разрешения браузера на камеру и микрофон.');
  } finally {
   if (session.current === room) setBusy(false);
  }
 }
 return <section className="lesson-call" aria-label="Видеосвязь">
  <p role="status">{status}</p>
  <div ref={media} className="lesson-call-media"/>
  <div className="lesson-call-actions">
   <button disabled={!room || busy} aria-pressed={microphone} onClick={() => void toggle('microphone')}>{microphone ? 'Выключить микрофон' : 'Включить микрофон'}</button>
   <button disabled={!room || busy} aria-pressed={camera} onClick={() => void toggle('camera')}>{camera ? 'Выключить камеру' : 'Включить камеру'}</button>
   {audioBlocked && room && <button onClick={() => void room.startAudio().catch(() => setStatus('Браузер заблокировал воспроизведение звука.'))}>Воспроизвести звук</button>}
   <button onClick={onClose}>Выйти</button>
  </div>
 </section>;
}
