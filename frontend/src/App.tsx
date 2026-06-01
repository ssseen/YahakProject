/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Camera, FileUp, Mic, Play, RefreshCw, Loader2, ChevronLeft, Volume2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

type PageState = 'MAIN' | 'CAMERA' | 'UPLOADED' | 'VOICE' | 'LOADING' | 'RESULT';

export default function App() {
  const [page, setPage] = useState<PageState>('MAIN');
  const [isListening, setIsListening] = useState(false);
  const [aiResponse, setAiResponse] = useState<string>("");
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const colors = {
    primary: '#2D5A27', // Stable Green
    lightGreen: '#EAF4E9',
    bg: '#FCFBF4', // Ivory/Off-white
    text: '#1A1A1A',
  };

  const transition = { type: 'spring' as const, damping: 25, stiffness: 120 };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setUploadedImage(reader.result as string);
        setPage('UPLOADED');
        setTimeout(() => setPage('VOICE'), 2000);
      };
      reader.readAsDataURL(file);
    }
  };

  const toggleVoiceRecognition = () => {
    if (isListening) {
      // Manual stop
      setIsListening(false);
      setPage('LOADING');
      fetchAiExplanation();
    } else {
      // Start listening
      setIsListening(true);
    }
  };

const fetchAiExplanation = async () => {
    try {
      setPage('LOADING'); // 로딩 화면으로 먼저 전환
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          image: uploadedImage, 
          userQuestion: "이 문제에 대해 다정하게 설명해주세요." 
        }),
      });

      const data = await res.json();
      
      // [수정 포인트] data.explanation이 서버에서 보내는 실제 해설입니다.
      if (data.explanation) {
        setAiResponse(data.explanation);
        setPage('RESULT');
      } else {
        throw new Error("해설 데이터를 받지 못했습니다.");
      }
    } catch (error) {
      console.error("분석 중 오류 발생:", error);
      setAiResponse("죄송해요 어르신, 선생님이 잠시 자리를 비우셨나 봐요. 다시 한번 찍어주실래요?");
      setPage('RESULT');
    }
  };
  const reset = () => {
    setPage('MAIN');
    setAiResponse("");
    setUploadedImage(null);
    setIsListening(false);
  };

  return (
    <div 
      className="min-h-screen flex items-center justify-center p-4" 
      style={{ backgroundColor: 'var(--color-ivory)', color: 'var(--color-forest)' }}
    >
      <div className="relative w-[360px] h-[740px] bg-white shadow-2xl rounded-[40px] overflow-hidden border-[12px] border-slate-800 flex flex-col">
        
        {/* Header */}
        {(page === 'VOICE' || page === 'RESULT') && (
          <header className="p-4 border-b border-mint flex items-center justify-between bg-white z-10">
            <button 
              onClick={() => setPage('MAIN')}
              className="text-forest hover:scale-110 active:scale-90 transition-transform"
            >
              <ChevronLeft size={32} />
            </button>
            <h1 className="text-forest text-xl font-bold">AI 선생님</h1>
            <div className="w-8" />
          </header>
        )}

        <main className="flex-1 overflow-y-auto relative bg-[#FDFCF0]">
          <AnimatePresence mode="wait">
            
            {/* 1. Main Page */}
            {page === 'MAIN' && (
              <motion.div 
                key="main"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex-1 flex flex-col items-center justify-center p-8 h-full"
              >
                <div className="text-center mb-12">
                  <h1 className="text-4xl font-bold text-forest leading-tight mb-2">AI 공부 친구</h1>
                  <p className="text-xl text-gray-600">무엇이든 물어보세요</p>
                </div>

                <button 
                  onClick={() => setPage('CAMERA')}
                  className="w-full aspect-square rounded-full flex flex-col items-center justify-center mb-10 border-4 border-forest shadow-lg active:scale-95 transition-transform"
                  style={{ backgroundColor: 'var(--color-mint)' }}
                  id="btn-camera"
                >
                  <Camera size={80} className="text-forest" />
                  <span className="text-3xl font-bold text-forest mt-4">카메라 켜기</span>
                </button>

                <button 
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full py-6 rounded-2xl bg-forest text-white text-2xl font-bold shadow-md active:opacity-90 transition-opacity"
                  id="btn-upload"
                >
                  사진 파일 선택
                </button>
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  className="hidden" 
                  accept="image/*"
                  onChange={handleFileUpload}
                />
              </motion.div>
            )}

            {/* 2. Camera Placeholder */}
            {page === 'CAMERA' && (
              <motion.div 
                key="camera"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="absolute inset-0 z-20 bg-black flex flex-col"
              >
                <div className="flex-1 border-x-4 border-white opacity-50 flex items-center justify-center">
                  <p className="text-white text-xl text-center px-10">책의 문제를<br/>화면에 맞춰주세요</p>
                </div>
                <div className="h-40 bg-black flex items-center justify-center gap-10">
                  <button 
                    onClick={() => setPage('MAIN')}
                    className="text-white text-xl font-medium"
                  >
                    취소
                  </button>
                  <button 
                    onClick={() => {
                      setPage('UPLOADED');
                      setTimeout(() => setPage('VOICE'), 2000);
                    }}
                    className="w-20 h-20 bg-white rounded-full border-4 border-gray-400 active:scale-90 transition-transform"
                  />
                  <div className="w-10" />
                </div>
              </motion.div>
            )}

            {/* 2b. Upload Success */}
            {page === 'UPLOADED' && (
              <motion.div 
                key="uploaded"
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-center justify-center h-full text-center space-y-6 p-8"
              >
                <div className="w-32 h-32 rounded-full bg-mint flex items-center justify-center">
                  <FileUp size={64} className="text-forest" />
                </div>
                <h2 className="text-3xl font-bold text-forest">사진을 잘 받았어요!</h2>
                <p className="text-xl text-gray-500">잠시만 기다려주세요...</p>
              </motion.div>
            )}

            {/* 3. Voice Recognition */}
            {page === 'VOICE' && (
              <motion.div 
                key="voice"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-center justify-center p-8 h-full"
              >
                <h2 className="text-3xl font-bold text-forest mb-12 text-center leading-tight">궁금한 것을<br/>말씀해주세요</h2>
                
                <button 
                  onClick={toggleVoiceRecognition}
                  className={`w-48 h-48 rounded-full bg-white flex items-center justify-center shadow-2xl border-4 border-forest transition-all ${isListening ? 'animate-pulse-green' : 'active:scale-95'}`}
                  id="btn-mic"
                >
                  <Mic size={80} className="text-forest" />
                </button>

                <p className={`mt-8 text-2xl font-semibold transition-colors duration-500 ${isListening ? 'text-forest' : 'text-gray-500'}`}>
                  {isListening ? "다 말씀하셨으면 마이크를 다시 눌러주세요" : "버튼을 눌러주세요"}
                </p>
              </motion.div>
            )}

            {/* 4. Loading */}
            {page === 'LOADING' && (
              <motion.div 
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-center justify-center p-8 h-full text-center"
              >
                <div className="w-32 h-32 bg-mint rounded-full flex items-center justify-center mb-10">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                  >
                    <Loader2 size={64} className="text-forest" />
                  </motion.div>
                </div>
                <h2 className="text-3xl font-bold text-forest leading-relaxed mb-8">선생님이 문제를<br/>읽고 있어요...</h2>
                <div className="w-full bg-gray-200 rounded-full h-6 overflow-hidden">
                  <motion.div 
                    className="bg-forest h-full"
                    initial={{ width: "0%" }}
                    animate={{ width: "100%" }}
                    transition={{ duration: 4, ease: "easeInOut" }}
                  />
                </div>
                <p className="mt-4 text-xl text-gray-500 font-medium">잠시만 기다려주세요~</p>
              </motion.div>
            )}

            {/* 5. Result */}
            {page === 'RESULT' && (
              <motion.div 
                key="result"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-6 h-full flex flex-col"
              >
                <div className="rounded-3xl overflow-hidden mb-6 border-4 border-mint shadow-md h-48 bg-gray-100 flex-shrink-0">
                  {uploadedImage ? (
                    <img src={uploadedImage} alt="Captured" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-400">
                      [ 찍은 사진 보기 ]
                    </div>
                  )}
                </div>

                <div className="bg-white p-6 rounded-3xl shadow-sm border border-mint mb-6 overflow-y-auto flex-1">
                  <h3 className="text-xl font-bold text-forest mb-2">AI 선생님의 한마디</h3>
                  <div className="text-2xl leading-snug font-medium text-slate-800 prose prose-forest">
                    <ReactMarkdown>{aiResponse}</ReactMarkdown>
                  </div>
                </div>

                <div className="space-y-4 flex-shrink-0">
                  <button 
                    onClick={() => {}} 
                    className="w-full py-6 rounded-2xl bg-mint text-forest text-2xl font-bold flex items-center justify-center gap-3 active:opacity-90 transition-opacity border-2 border-forest"
                    id="btn-listen-again"
                  >
                    <Volume2 size={32} />
                    음성 다시 듣기
                  </button>
                  <button 
                    onClick={reset}
                    className="w-full py-6 rounded-2xl bg-forest text-white text-2xl font-bold active:opacity-90 transition-opacity border-2 border-forest"
                    id="btn-restart"
                  >
                    처음으로 가기
                  </button>
                </div>
              </motion.div>
            )}

          </AnimatePresence>
        </main>
      </div>

      <style>{`
        .prose strong {
          color: var(--color-forest);
          font-weight: 800;
        }
      `}</style>
    </div>
  );
}

