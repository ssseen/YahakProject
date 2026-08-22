// HTML에 있는 마이크 버튼 가져오기
const micBtn = document.querySelector('.mic-btn'); 

let mediaRecorder;
let audioChunks = [];

// 1. 마이크 접근 권한 요청
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => {
    mediaRecorder = new MediaRecorder(stream);

    // 녹음 중일 때 소리 조각들을 차곡차곡 모음
    mediaRecorder.ondataavailable = event => {
      audioChunks.push(event.data);
    };

    // 2. 녹음이 끝났을 때 실행될 로직 (핵심!)
    mediaRecorder.onstop = async () => {
      // 모아둔 소리 조각들을 하나의 오디오 파일(webm)로 뭉치기
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
      audioChunks = []; // 다음 녹음을 위해 초기화

      // 백엔드로 보낼 택배 상자(FormData)에 오디오 파일 담기
      const formData = new FormData();
      formData.append("audio_file", audioBlob, "record.webm");

      console.log("🚀 서버로 음성 파일 배달 시작!");

      // 3. 백엔드(FastAPI) API로 쏘기!
      const response = await fetch("http://localhost:8000/transcribe", {
        method: "POST",
        body: formData
      });
      
      // 4. 위스퍼가 번역해서 돌려준 텍스트 받기
      const result = await response.json();
      console.log("🎯 변환된 사투리 텍스트:", result.text);
      
      // (여기에 result.text를 화면에 보여주는 코드 추가)
    };
  });

// 버튼 클릭 시 녹음 시작/종료 컨트롤
micBtn.addEventListener('click', () => {
  if (mediaRecorder.state === 'inactive') {
    mediaRecorder.start();
    micBtn.textContent = '녹음 중지'; // UI 변경
  } else {
    mediaRecorder.stop(); // 녹음이 중지되면 자동으로 위쪽의 onstop 로직이 실행됨
    micBtn.textContent = '마이크 버튼';
  }
});