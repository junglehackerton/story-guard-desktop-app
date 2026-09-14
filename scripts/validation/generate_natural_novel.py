"""Generate a non-repeating Korean serial-fiction fixture with known continuity cases."""
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/validation/natural-novel-20260914/episodes'
MANIFEST=OUT.parent/'manifest.json'
EPISODES=[
('비가 멎은 뒤','폐역의 시계를 되돌린 유나가 은빛 열쇠와 첫 기록을 발견한다','폐역 승강장','은빛 열쇠','도윤'),
('첫 번째 계약','도윤이 감시자의 규칙을 설명하고 유나는 서명하지 않은 계약서를 숨긴다','회백원 서고','계약 규칙','도윤'),
('붉은 지도','서린이 지도에 없는 골목을 안내하고 문지기의 거짓말을 추적한다','흰 재 시장','붉은 지도','서린'),
('잠긴 수로','마루의 배가 멈춘 수로에서 열쇠 문양과 오래된 수문을 대조한다','침수된 수로','수문 문양','마루'),
('밤의 도서관','하린이 삭제 목록에서 유나의 이름을 읽고 도윤의 설명과 충돌한다','밤의 도서관','삭제 목록','하린'),
('흰 재의 축제','축제의 불꽃 아래 서린이 숨긴 편지가 사라지고 동맹이 갈라진다','흰 재 광장','사라진 편지','서린'),
('돌아오지 않는 배','마루가 금지 항로로 떠난 뒤 연락이 끊기고 유나는 열쇠를 사용한다','해무 선착장','금지 항로','마루'),
('세 번째 문','하린의 기억 속 문이 열리며 계약의 예외 조항이 모습을 드러낸다','검은 종루','예외 조항','하린'),
('종루 아래','백야회가 종루를 포위하고 도윤이 감시자였다는 사실을 고백한다','종루 지하 회랑','감시자의 표식','도윤'),
('새벽의 선택','유나가 계약을 찢을지 지킬지 선택하고 편지의 마지막 문장을 완성한다','새벽 항구','마지막 문장','유나'),]
BEATS=['유나는 현장에서 본 것과 기록에 남은 것을 노란 수첩의 서로 다른 면에 적었다.','도윤은 질문을 피하려고 했지만 피하는 방식 자체가 새로운 단서가 되었다.','서린은 사람들의 말을 그대로 믿지 않고 누가 언제 그 말을 들었는지부터 확인했다.','마루는 물길과 바람의 방향을 지도에 표시하며 사라진 항로를 역산했다.','하린은 기억이 틀릴 수 있다는 사실을 인정한 뒤에도 숫자와 순서는 끝까지 지켰다.','그날의 기록에는 사건보다 사건을 설명하려는 사람들의 태도가 더 선명하게 남았다.','유나는 확정된 사실에는 초록 실을 추측에는 황갈색 실을 묶어 서로 섞이지 않게 했다.','누군가의 진술은 앞선 장면과 맞았지만 장소 하나가 달라 모두가 다시 계산해야 했다.','낡은 종이의 냄새가 사라질 때까지 일행은 누구도 결론이라는 말을 입 밖에 내지 않았다.','창문 밖의 종소리는 일정한 간격으로 이어졌고 그 간격이 다음 장소를 가리키는 듯했다.','기록관의 도장은 분명했지만 담당자의 이름만 칼로 긁혀 있어 출처를 확정할 수 없었다.','유나는 같은 질문을 다른 사람에게 건네 답변의 차이를 표로 만들었다.','도윤은 규칙의 예외를 말하지 않았고 그 침묵은 규칙보다 오래 남았다.','서린은 봉투의 접힌 모서리를 보고 누군가 내용을 읽고 다시 봉했다는 생각을 했다.','마루가 남긴 매듭은 돌아오라는 신호가 아니라 항구에 접근하지 말라는 경고였다.','하린은 계단의 발자국 수를 세고 기억 속 장면과 실제 건물의 높이를 비교했다.','밤이 깊어질수록 단서는 가까워졌지만 서로를 설명해 주지는 않았다.','일행은 증거가 없는 문장을 회의록에서 지우지 않고 보류 표시를 붙였다.','누군가는 그 흔적을 우연이라 불렀고 유나는 우연이라고 부르기 전에 반복을 확인했다.','비가 그친 뒤 벽에 남은 물자국은 지도에 없는 길처럼 천천히 방향을 바꾸었다.','등불을 든 사람의 그림자가 실제 사람보다 먼저 골목을 통과했다.','유나는 자신의 판단도 틀릴 수 있다는 문장을 기록의 맨 아래에 덧붙였다.']
DETAILS=['젖은 표지판의 숫자','봉인 가장자리의 흰 가루','지도에서 지워진 골목','수문의 세 번째 홈','삭제 목록의 빈 줄','불꽃이 꺼진 뒤 남은 재','돌아오지 않은 배의 밧줄','문 안쪽의 세 계단','감시자의 검은 표식','편지 마지막 줄의 빈칸']
ACTIONS=['시각과 위치를 따로 기록했다','낡은 열쇠의 톱니를 종이에 눌러 본을 떴다','서명란을 비워 둔 채 다음 증인을 찾았다','문지기의 말을 녹음 대신 필사했다','수문 손잡이의 방향을 두 번 확인했다','삭제 목록의 앞뒤 이름을 대조했다','편지의 접힌 순서를 그림으로 남겼다','항로의 좌표를 배의 흔들림과 함께 계산했다','계단 수와 기억 속 계단 수를 나란히 적었다','표식의 모양을 다른 기록과 비교했다']
ENDINGS=['아직 결론으로 분류하지 않았다.','다음 증언이 올 때까지 보류하기로 했다.','확정란 대신 물음표를 남겼다.','서로 다른 설명을 모두 기록에 보존했다.','그날 밤에는 누구도 판단을 서두르지 않았다.']
SUBJECT={'유나':'유나는','도윤':'도윤은','서린':'서린은','마루':'마루는','하린':'하린은'}
DETAIL_PARTICLE={'젖은 표지판의 숫자':'를','봉인 가장자리의 흰 가루':'를','지도에서 지워진 골목':'을','수문의 세 번째 홈':'을','삭제 목록의 빈 줄':'을','불꽃이 꺼진 뒤 남은 재':'를','돌아오지 않은 배의 밧줄':'을','문 안쪽의 세 계단':'을','감시자의 검은 표식':'을','편지 마지막 줄의 빈칸':'을'}
PLACE_PARTICLE={'폐역 승강장':'을','회백원 서고':'를','흰 재 시장':'을','침수된 수로':'를','밤의 도서관':'을','흰 재 광장':'을','해무 선착장':'을','검은 종루':'를','종루 지하 회랑':'을','새벽 항구':'를'}
DIALOGUES={
 '유나':['"기록에 없는 말은 아직 사실이 아니에요. 하지만 없던 일로 지울 수도 없죠."','"내가 본 장면과 당신이 기억하는 장면이 다르다면, 먼저 장소부터 다시 확인해요."'],
 '도윤':['"감시자의 규칙은 간단합니다. 정식 계약자만 봉인검을 사용할 수 있습니다."','"예외를 묻지 마십시오. 예외를 말하는 순간 규칙은 더 이상 방패가 아니니까요."'],
 '서린':['"지도에 길이 없다는 건 길이 없다는 뜻이 아니에요. 누군가 지웠다는 뜻일 수도 있죠."','"그 사람의 말보다, 그 말을 하기 직전에 숨긴 손을 봐야 해요."'],
 '마루':['"물은 거짓말을 안 해. 다만 우리가 읽는 방향을 바꿀 뿐이지."','"배가 떠난 흔적은 남아 있어. 돌아오지 않았다는 말과 돌아올 수 없었다는 말은 달라."'],
 '하린':['"기억은 흔들려도 숫자는 남아요. 세 번째 문이라는 사실부터 놓치지 마세요."','"삭제된 이름 옆의 빈칸이 오히려 가장 큰 증거일 수 있어요."'],
}

def make_episode(index,title,synopsis,place,clue,actor):
    ps=[f'제{index}화 〈{title}〉\n\n{synopsis}.']
    for n in range(61):
        beat=BEATS[(index*5+n)%len(BEATS)]; detail=DETAILS[(index+n)%len(DETAILS)]
        action=ACTIONS[(index+n)%len(ACTIONS)]
        actor_subject=SUBJECT[actor]
        detail_obj=detail+DETAIL_PARTICLE[detail]
        place_obj=place+PLACE_PARTICLE[place]
        forms = [
            f'{beat} {place}의 {detail_obj} 확인한 {actor_subject} {action}.',
            f'{actor_subject} {place}에서 {detail_obj} 발견하고 한참 말이 없었다. 유나는 그 침묵을 {clue}에 대한 두려움으로 단정하지 않고 {action}.',
            f'기록의 여백에는 {detail}에 대한 서로 다른 설명이 남아 있었다. {actor_subject} {action}.',
            f'{place_obj} 빠져나오기 전 {actor_subject} 동료들에게 {detail_obj} 보여 주었다. 의견은 갈렸지만 유나는 {action}.',
        ]
        # Keep every paragraph distinct so retrieval tests can tell apart nearby
        # evidence. The small notebook sequence is an in-world habit, rather
        # than an artificial QA label.
        sequence_note = f'유나는 수첩 가장자리에 오늘 기록의 순서를 뜻하는 {n + 1}이라는 숫자를 눌러 두었다.'
        ps.append(forms[n % len(forms)] + ' ' + ENDINGS[(index + n) % len(ENDINGS)] + ' ' + sequence_note)
        if n % 3 == 0:
            line = DIALOGUES[actor][(n // 3 + index) % len(DIALOGUES[actor])]
            reply = DIALOGUES['유나'][(n + index) % len(DIALOGUES['유나'])] if actor != '유나' else DIALOGUES['도윤'][(n + index) % len(DIALOGUES['도윤'])]
            ps.append(f'{actor_subject} {line} {reply} 상대는 바로 대답하지 못했고, 유나는 그 침묵의 길이까지 기록했다. 이번 대화는 {n + 1}번째 확인 절차 뒤에 이어졌다.')
        if n%4==1: ps.append(f'유나는 {index+n+1}번째 메모에 {clue}의 등장 시각과 주변 인물의 말을 함께 적었다. 앞선 기록과 다른 점은 지우지 않고 물음표를 남겼다. 그 메모의 가장자리에는 {n + 1}번째 순서라는 표시가 남았다.')
        if n%7==3: ps.append(f'{place}의 문이 닫힌 뒤에도 일행은 각자의 기억을 대조했다. 같은 장면을 서로 다르게 말하는 사람이 있어 다음 행동은 보류되었다. 유나는 이 대조를 {n + 1}번째 확인 절차로 기록했다.')
    if index==2: ps.append('도윤은 정식 계약자만 봉인검을 사용할 수 있다고 단언했다.')
    if index==4: ps.append('마루는 해무 선착장을 떠났다고 기록되었지만 다음 장면의 도서관 창가에서 목격되었다.')
    if index==7: ps.append('유나는 계약서에 서명하지 않았지만 봉인검을 꺼내 수로의 문을 열었다.')
    if index==10: ps.append('사라진 편지는 마지막 문장을 남겼지만 첫 장의 붉은 실밥이 누구의 것인지는 끝내 밝혀지지 않았다.')
    return '\n\n'.join(ps)+'\n'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for i,data in enumerate(EPISODES,1): (OUT/f'episode-{i:02d}.txt').write_text(make_episode(i,*data),encoding='utf-8')
    manifest={'fixture':'natural-serial-v2','episodes':10,'expected_findings':[
      {'type':'setting_conflict','episodes':[2,7],'claim':'봉인검은 정식 계약자만 사용할 수 있음 / 비계약자인 유나가 사용'},
      {'type':'continuity_gap','episodes':[4,5],'claim':'마루가 항구를 떠난 뒤 설명 없이 도서관에 등장'},
      {'type':'unresolved_foreshadowing','episodes':[1,6,10],'claim':'붉은 실밥의 주인이 끝까지 밝혀지지 않음'},
      {'type':'resolved_foreshadowing','episodes':[1,10],'claim':'은빛 열쇠가 마지막 문장을 여는 단서로 회수됨'}]}
    MANIFEST.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'generated {len(EPISODES)} chapters in {OUT}')
if __name__=='__main__': main()
