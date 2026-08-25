# FrameLab

FrameLab은 설치된 Codex와 현재 ChatGPT/Codex 로그인을 사용해 여러 사진을 스타일 변환하는 로컬 데스크톱 프로그램입니다. OpenAI API 키를 별도로 사용하지 않습니다.

## 다른 컴퓨터에서 실행

필수 조건:

- Git
- Node.js 20 이상
- Python 3
- 설치 및 로그인된 ChatGPT 또는 Codex 데스크톱 앱
- Codex의 기본 `imagegen` 스킬

```bash
git clone https://github.com/redalert-oss/framlab.git
cd framlab
npm run setup
npm start
```

Codex에게는 저장소 주소와 함께 다음처럼 요청하면 됩니다.

> 이 저장소를 내려받아 `npm run setup`으로 점검하고 FrameLab을 실행해줘.

### 간편 실행

- macOS: `start.command`를 실행하거나 `npm start`
- Windows: `start-windows.bat`를 실행하거나 `npm start`

환경 점검만 다시 실행하려면 다음 명령을 사용합니다.

```bash
npm run check
```

## 주요 기능

- JPEG, PNG, WebP 사진을 한 번에 최대 8장 불러오기
- 펠트 미니미, 감성 수채화, 핀터 손그림, 빈티지 포스터 변환
- 스타일별 미리보기 썸네일
- 원본과 결과 이미지 비교
- 작업 기록과 결과 다운로드
- 프로그램 안에서 프롬프트 확인·수정
- 결과 폴더와 프롬프트 폴더 바로 열기

## 빌드

macOS용 앱과 설치 파일:

```bash
npm run build:mac
```

Windows portable 실행 파일은 Windows에서 빌드합니다.

```bash
npm run build:win
```

현재 macOS와 Windows 빌드는 개발자 인증서로 서명·공증되지 않은 로컬 테스트 빌드입니다.

## 데이터 저장

프리셋 수정본, 작업 기록, 원본 복사본과 변환 결과는 Git 저장소가 아니라 운영체제의 FrameLab 사용자 데이터 폴더에 저장됩니다. 다음 데이터는 Git에 올리지 않습니다.

- 사용자가 불러온 사진
- 변환 결과와 작업 기록
- `node_modules/`, `.pnpm-store/`, `dist/`
- Codex 로그인 세션과 토큰
- `.env` 및 로컬 설정

`presets/`에는 새 설치 시 복사되는 기본 프롬프트가 들어 있습니다. `photo-edit-assets/`에는 프로그램 화면에서 사용하는 기본 미리보기 이미지만 포함됩니다.

## 참고

- 한 장 변환에는 수십 초에서 수 분이 걸릴 수 있습니다.
- 사용량은 로그인된 ChatGPT/Codex 플랜의 사용 한도에 포함될 수 있습니다.
- Codex의 실험적 `app-server` 연동을 사용하므로 Codex 업데이트 뒤 호환성 확인이 필요할 수 있습니다.
