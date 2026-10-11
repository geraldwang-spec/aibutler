"""Explicit exercise-to-photo mappings; never guess from partial names.

Media is bundled locally. Unknown/custom exercises remain visibly unmatched.
"""
from pathlib import Path
import re

MEDIA_ROOT = Path(__file__).resolve().parents[1] / 'static' / 'exercise-media'
EXERCISE_MEDIA = {
    '槓鈴臥推': 'Barbell_Bench_Press_-_Medium_Grip',
    '上斜槓鈴臥推': 'Barbell_Incline_Bench_Press_-_Medium_Grip',
    '下斜槓鈴臥推': 'Decline_Barbell_Bench_Press',
    '啞鈴臥推': 'Dumbbell_Bench_Press',
    '上斜啞鈴臥推': 'Incline_Dumbbell_Press',
    '啞鈴飛鳥': 'Dumbbell_Flyes',
    '史密斯臥推': 'Smith_Machine_Bench_Press',
    '機械胸推': 'Machine_Bench_Press',
    '蝴蝶機夾胸': 'Butterfly',
    '纜繩夾胸': 'Cable_Crossover',
    '伏地挺身': 'Pushups',
    '雙槓撐體': 'Dips_-_Chest_Version',
    '硬舉': 'Barbell_Deadlift',
    '槓鈴划船': 'Bent_Over_Barbell_Row',
    'T 槓划船': 'T-Bar_Row_with_Handle',
    '單臂啞鈴划船': 'One-Arm_Dumbbell_Row',
    '滑輪下拉': 'Wide-Grip_Lat_Pulldown',
    '坐姿划船': 'Seated_Cable_Rows',
    '直臂下拉': 'Straight-Arm_Pulldown',
    '機械划船': 'Leverage_Iso_Row',
    '引體向上': 'Pullups',
    '反手引體向上': 'Chin-Up',
    '背部伸展': 'Hyperextensions_Back_Extensions',
    '單臂坐姿滑輪划船': 'Seated_One-arm_Cable_Pulley_Rows',
    '低位划船機': 'Leverage_Iso_Row',
    '槓鈴深蹲': 'Barbell_Squat',
    '前蹲舉': 'Front_Barbell_Squat',
    '羅馬尼亞硬舉': 'Romanian_Deadlift',
    '槓鈴臀推': 'Barbell_Hip_Thrust',
    '高腳杯深蹲': 'Goblet_Squat',
    '啞鈴弓步蹲': 'Dumbbell_Lunges',
    '保加利亞分腿蹲': 'Split_Squat_with_Dumbbells',
    '腿推舉': 'Leg_Press',
    '哈克深蹲': 'Hack_Squat',
    '腿伸屈': 'Leg_Extensions',
    '腿彎舉': 'Lying_Leg_Curls',
    '站姿提踵': 'Standing_Calf_Raises',
    '徒手深蹲': 'Bodyweight_Squat',
    '登階': 'Step-up_with_Knee_Raise',
    '槓鈴肩推': 'Barbell_Shoulder_Press',
    '直立划船': 'Upright_Barbell_Row',
    '啞鈴肩推': 'Dumbbell_Shoulder_Press',
    '阿諾肩推': 'Arnold_Dumbbell_Press',
    '啞鈴側平舉': 'Side_Lateral_Raise',
    '啞鈴前平舉': 'Front_Dumbbell_Raise',
    '啞鈴反向飛鳥': 'Seated_Bent-Over_Rear_Delt_Raise',
    '啞鈴聳肩': 'Dumbbell_Shrug',
    '機械肩推': 'Leverage_Shoulder_Press',
    '纜繩側平舉': 'Standing_Low-Pulley_Deltoid_Raise',
    '臉拉': 'Face_Pull',
    '槓鈴彎舉': 'Barbell_Curl',
    '窄握臥推': 'Close-Grip_Barbell_Bench_Press',
    'EZ 槓彎舉': 'EZ-Bar_Curl',
    '牧師椅彎舉': 'Preacher_Curl',
    '仰臥三頭伸展': 'Lying_Triceps_Press',
    '啞鈴彎舉': 'Dumbbell_Bicep_Curl',
    '錘式彎舉': 'Hammer_Curls',
    '啞鈴過頭三頭伸展': 'Standing_Dumbbell_Triceps_Extension',
    '纜繩彎舉': 'Standing_Biceps_Cable_Curl',
    '纜繩下壓': 'Triceps_Pushdown',
    '板凳撐體': 'Bench_Dips',
    '捲腹': 'Crunches',
    '仰臥抬腿': 'Flat_Bench_Lying_Leg_Raise',
    '懸吊舉腿': 'Hanging_Leg_Raise',
    '俄羅斯轉體': 'Russian_Twist',
    '健腹輪': 'Ab_Roller',
    '纜繩捲腹': 'Cable_Crunch',
}

VARIANT_NOTES = {
    '高腳杯深蹲': '圖中為壺鈴版本；你的動作庫記錄為啞鈴，握持方式不同。',
    '登階': '圖中示範登階接抬膝的變化式。',
    '低位划船機': '圖中為槓片式划船機；實際器械的握把與軌跡可能不同。',
    '啞鈴反向飛鳥': '圖中為坐姿俯身版本。',
    '仰臥抬腿': '圖中為平板凳版本。',
}


def media_for(name):
    normalized = re.sub(r'\s+', '', str(name or '')).casefold()
    match = next((key for key in EXERCISE_MEDIA
                  if re.sub(r'\s+', '', key).casefold() == normalized), None)
    if not match:
        return None
    slug = EXERCISE_MEDIA[match]
    paths = [f'exercise-media/{slug}/{i}.jpg' for i in range(2)]
    if not all((MEDIA_ROOT / slug / f'{i}.jpg').is_file() for i in range(2)):
        return None
    return {'images': paths, 'note': VARIANT_NOTES.get(match, ''), 'source_id': slug}
