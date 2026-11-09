# Excel 배포 전용 schema76 복구 후보

기준 b9007cbd의 사용자 기능을 유지하며 additive 0075/0076 DB에서 readiness를
확인하는 후보다. 운영 활성화 승인이 아니며 새 Excel UI/API 기능은 없다.
원본 migration bytes와 migration head만 추가한다. 기존 0074 테이블/행은 바꾸지 않는다.

복구는 새 Excel을 사용자에게 공개하거나 새 편성 기록을 저장하기 **전**에만 사용한다.
공개 후에는 새 이력을 보존하는 호환 forward fix가 필요하다. DB downgrade나 이력 삭제는
하지 않는다. 기존 INDEX/GPU 설치본·진행 작업은 변경하지 않는다.

검증은 같은 non-editable wheel build/RECORD, 실제 0076 disposable DB의 기존 use case
회귀 및 migration head 확인으로 한다. rollback provider의 source/wheel/member pins도
이 commit의 설치본으로 다시 구성해야 한다.
