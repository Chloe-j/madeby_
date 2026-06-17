/**
 * 일일 업무 카운터 - 구글 스프레드시트 연동용 Apps Script
 *
 * [설치 방법]
 * 1. 데이터를 쌓을 구글 스프레드시트를 엽니다 (또는 새로 만듭니다).
 * 2. 상단 메뉴 [확장 프로그램] > [Apps Script] 클릭
 * 3. 기존 코드를 모두 지우고 이 코드를 전체 붙여넣기
 * 4. 저장 (Ctrl+S 또는 저장 아이콘)
 * 5. 우측 상단 [배포] > [새 배포] 클릭
 *    - 유형 선택: "웹 앱" 선택
 *    - 설명: 아무거나 (예: 업무카운터)
 *    - 다음 액세스 권한이 있는 사용자: "나만" (본인만 쓸 거면) 선택
 *    - 실행 사용자: "나" 선택
 *    - [배포] 클릭 → 권한 승인 (본인 계정으로 승인)
 * 6. 배포 완료 후 나오는 "웹 앱 URL"을 복사
 * 7. 카운터 앱(HTML)의 설정 화면에 그 URL을 붙여넣고 저장
 *
 * 코드를 수정한 뒤에는 [배포] > [배포 관리] > 수정(연필 아이콘) > 새 버전으로 다시 배포해야
 * 변경사항이 실제 URL에 반영됩니다.
 */

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);

    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

    // 헤더가 없으면 첫 줄에 헤더를 추가
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(['날짜', '설치/탈거', 'A/S', '계약', '그 외', '메모', '전송시각']);
    }

    sheet.appendRow([
      data.date || '',
      data.install_removal || 0,
      data.as || 0,
      data.contract || 0,
      data.etc || 0,
      data.memo || '',
      new Date()
    ]);

    return ContentService
      .createTextOutput(JSON.stringify({ result: 'success' }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ result: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: 'ok', message: '이 URL은 POST 요청만 처리합니다.' }))
    .setMimeType(ContentService.MimeType.JSON);
}
