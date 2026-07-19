import csv
import json
import os
import random
import re

import math
import numpy as np
from sklearn.metrics import f1_score, accuracy_score

os.environ['CUDA_VISIBLE_DEVICES'] = '1'
import argparse
from . import model_init, mm_infer
from utils import disable_torch_init
from transformers import BertTokenizer
from peft import PeftModel

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", required=False, type=str, default="CMU_MOSI")
parser.add_argument("--evaluate_type", required=False, type=str, default="miss_rate")
parser.add_argument("--model_path", required=False, type=str, default=None)
args = parser.parse_args()

DATASET = args.dataset

# 噪声文件
TEXT_NOISE_FILES = ["neutral_text.json", "random_insert_text.json", "shuffled_text.json", "typo_noise_text.json"]
AUDIO_NOISE_FILES = ["audio_meeting_noise", "audio_river_noise", "audio_silent", "audio_traffic_noise",
                     "audio_white_noise"]
VIDEO_NOISE_FILES = ["video_black", "video_blur", "video_gaussian", "video_salt_pepper"]


def binomial_probability(U, k, MP):
    """计算二项分布概率 p(k)"""
    comb = math.comb(U, k)
    return comb * (MP ** k) * ((1 - MP) ** (U - k))


def calculate_MP_probabilities(MP, type="miss"):
    """计算归一化的缺失概率"""
    U = 3  # 模态数量：text, audio, visual
    probabilities = []
    if type == "miss":
        for k in range(3):
            p_k = binomial_probability(U, k, MP)
            probabilities.append(p_k)
    elif type == "noise":
        for k in range(4): # 0, 1, 2, 3
            p_k = binomial_probability(U, k, MP)
            probabilities.append(p_k)
    else:
        raise ValueError('Unknown type')
    total_prob = sum(probabilities)
    normalized_probabilities = [p / total_prob for p in probabilities]
    return normalized_probabilities


def ensure_one_modal_false(temp_results):
    modify_num = 0
    for item in temp_results:
        true_num = item.count(True)
        if true_num == 3:
            # 所有模态为 True，随机选取一个模态为 False
            random_index = random.randint(0, 2)
            item[random_index] = False
            modify_num += 1
    # 第二次遍历：根据修改次数 modify_num 补充 True
    for item in temp_results:
        true_num = item.count(True)
        if true_num == 1:
            # 可补充一个 True
            if modify_num > 0:
                # 需要补充一个 True
                random_index = random.randint(0, 2)
                while item[random_index] == True:  # 确保不覆盖已有的 True
                    random_index = random.randint(0, 2)
                item[random_index] = True
                modify_num -= 1
        if true_num == 0:
            # 可补充两个 True
            if modify_num == 1:
                # 需要补充一个 True
                random_index = random.randint(0, 2)
                item[random_index] = True
                modify_num -= 1
            if modify_num > 1:
                # 需要补充两个 True
                random_indexs = random.sample(range(3), 2)
                item[random_indexs[0]] = True
                item[random_indexs[1]] = True
                modify_num -= 1

    return temp_results


def generate_miss_rate(miss_rate, data_len):
    """
    在测试阶段，对每个样本随机缺失 0、1 或 2 个模态，使用 缺失率（Missing Rate, MR）衡量整个数据集的模态缺失程度。
    miss_rate 在 [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7] 中选取，当 MR = 0.7 时，意味着每个样本仅保留 1 个模态
    """
    # 生成长度为 3 * test_data_len 的一维列表（TVA 3个模态）
    modalities = [False] * (3 * data_len)

    # 随机选择缺失的部分
    num_missing = int(len(modalities) * miss_rate)  # 缺失的模态数量
    missing_indices = random.sample(range(len(modalities)), num_missing)
    missing_indices.sort()
    for idx in missing_indices:
        modalities[idx] = True
    temp_results = [modalities[i:i+3] for i in range(0, len(modalities), 3)]

    # 确保至少有一个模态为 False
    # 第一次遍历：找到所有模态为 True，随机选取一个模态为 False，并记录修改次数
    temp_results = ensure_one_modal_false(temp_results)

    # 输出结果
    results = [{"text": item[0], "audio": item[1], "visual": item[2]} for item in temp_results]

    return results


def generate_miss_probability(miss_probability, data_len):
    """
    在样本级别，使用 缺失概率（Missing Probability, MP）控制每个模态的缺失概率。每个样本中缺失 k 个模态的概率服从二项分布。
    """
    probabilities = calculate_MP_probabilities(miss_probability, type="miss")

    results = []
    for _ in range(data_len):
        modality_set = [False, False, False]  # 默认为全为False (text, audio, visual)

        # 根据缺失概率决定缺失的模态
        k = random.choices([0, 1, 2], probabilities)[0]  # 随机选择缺失的模态数
        # 随机选择k个模态为 True
        if k > 0:
            selected_indices = random.sample([0, 1, 2], k)
            for idx in selected_indices:
                modality_set[idx] = True
        results.append({
            "text": modality_set[0],
            "audio": modality_set[1],
            "visual": modality_set[2]
        })

    return results


def generate_noise_rate(noise_rate, data_len):
    """
    在测试阶段，对每个样本随机缺失 0、1 或 2 个模态，使用 缺失率（Missing Rate, MR）衡量整个数据集的模态缺失程度。
    noisy_rate 在 [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9] 中选取，不用确保至少有一个模态可用
    """
    # 生成长度为 3 * test_data_len 的一维列表（TVA 3个模态）
    modalities = [False] * (3 * data_len)

    # 随机选择缺失的部分
    num_missing = int(len(modalities) * noise_rate)  # 缺失的模态数量
    missing_indices = random.sample(range(len(modalities)), num_missing)
    missing_indices.sort()
    for idx in missing_indices:
        modalities[idx] = True
    temp_results = [modalities[i:i+3] for i in range(0, len(modalities), 3)]

    # 确保至少有一个模态为 False
    # 第一次遍历：找到所有模态为 True，随机选取一个模态为 False，并记录修改次数
    # temp_results = ensure_one_modal_false(temp_results)

    # 输出结果
    results = [{"text": item[0], "audio": item[1], "visual": item[2]} for item in temp_results]

    return results


def generate_noise_probability(noise_probability, data_len):
    """
    在样本级别，使用 缺失概率（Missing Probability, MP）控制每个模态的缺失概率。每个样本中缺失 k 个模态的概率服从二项分布。
    """
    probabilities = calculate_MP_probabilities(noise_probability, type="noise")

    results = []
    for _ in range(data_len):
        modality_set = [False, False, False]  # 默认为全为False (text, audio, visual)

        # 根据缺失概率决定缺失的模态
        k = random.choices([0, 1, 2, 3], probabilities)[0]  # 随机选择缺失的模态数
        # 随机选择k个模态为 True
        if k > 0:
            selected_indices = random.sample([0, 1, 2], k)
            for idx in selected_indices:
                modality_set[idx] = True
        results.append({
            "text": modality_set[0],
            "audio": modality_set[1],
            "visual": modality_set[2]
        })

    return results


def generate_miss_fixed(data_len, text=False, visual=False, audio=False):
    """
    要确保有一个模态不为 True
    """
    if text and visual and audio:
        raise ValueError('Cannot true both text and visual and audio')
    results = []
    for _ in range(data_len):
        results.append({
            "text": text,
            "audio": audio,
            "visual": visual
        })
    return results


def generate_noise_fixed(data_len, text=False, visual=False, audio=False):
    results = []
    for _ in range(data_len):
        results.append({
            "text": text,
            "audio": audio,
            "visual": visual
        })
    return results


def get_prompt(text):
    dataset = DATASET
    if dataset == 'sims' or dataset == 'simsv2':
        label_type = "sentiment"
        label_introduction = f"The {label_type} label is a sentiment score ranging from -1 to +1, where -1 indicates highly negative, +1 indicates highly positive, and 0 indicates neutral."
        example = "-0.2"
    elif dataset == 'mosi' or dataset == 'mosei':
        label_type = "sentiment"
        example = "0.4"
        label_introduction = f"The {label_type} label is a sentiment score ranging from -3 to +3, where -3 indicates highly negative, +3 indicates highly positive, and 0 indicates neutral."
    elif dataset == 'meld':
        label_type = "emotion"
        example = "sadness"
        label_introduction = f"The {label_type} label is one of the following seven emotions: anger, disgust, sadness, joy, neutral, surprise, and fear."
    elif dataset == 'urfunny2':
        label_type = "humor"
        example = "humorous"
        label_introduction = f"The {label_type} label include two situations: humorous and serious."

    prompt = (f"<video>\n<audio>\nYou are presented with a video in which the speaker says: {text}. \n"
              f"The {label_type} label introduction: {label_introduction}. \n"
              f"Based on the textual, visual, and audio content, what is the {label_type} label of this speaker? \n"
              f"Respond in the following format: {example}. \n"
              f"Provide only one label. ")

    return prompt


def get_model(model_path, lora_path=None):
    """
    获取模型
    """
    # 初始化BERT分词器
    bert_tokenizer = BertTokenizer.from_pretrained("bert-base-uncased")
    # 禁用Torch初始化
    disable_torch_init()
    # 初始化模型、处理器和分词器
    base_model, processor, tokenizer = model_init(model_path)
    # 若有 lora 微调则加载 lora 微调参数
    if lora_path is not None:
        model = PeftModel.from_pretrained(base_model, lora_path)
        model = model.merge_and_unload()
    else:
        model = base_model

    models = {
        "model": model,
        "tokenizer": tokenizer,
        "processor": processor,
        "bert_tokenizer": bert_tokenizer
    }

    return models


def predict(models, data_path, raw_data_dir):
    """
    预测
    """
    predict_results = []

    with open(data_path, mode='r', encoding='utf-8') as file:
        data = csv.DictReader(file)

        for item in data:
            if item['mode'] != 'test':
                continue

            text = item['text']
            video_path = os.path.join(raw_data_dir+"/video", item['id']+".mp4")
            audio_path = os.path.join(raw_data_dir+"/audio", item['id']+".wav")

            modal = "video_audio"
            video_tensor = models['processor']['video'](video_path)
            audio_tensor = models['processor']['audio'](audio_path)[0]

            # 输出预测
            prompt = get_prompt(text)
            output = mm_infer(video_tensor, prompt, model=models["model"], tokenizer=models["tokenizer"], modal=modal,
                              bert_tokeni=models["bert_tokenizer"], do_sample=False, audio=audio_tensor)

            predict_results.append(output)

    return predict_results


def miss_predict(models, data_path, raw_data_dir, miss_marks):
    """
    预测
    """
    predict_results = []

    with open(data_path, mode='r', encoding='utf-8') as file:
        data = csv.DictReader(file)

        for item, miss_item in zip(data, miss_marks):
            if item['mode'] != 'test':
                continue

            text = item['text']
            video_path = os.path.join(raw_data_dir+"/video", item['id']+".mp4")
            audio_path = os.path.join(raw_data_dir+"/audio", item['id']+".wav")

            modal = None
            video_tensor = None
            audio_tensor = None

            if miss_item["text"]:
                # 文本缺失
                text = ""

            if miss_item["visual"] and miss_item["audio"]:
                # 视觉和音频缺失
                modal = "text"
            elif miss_item["visual"]:
                # 只缺失视觉
                video_tensor = models['processor']['video'](video_path)
                modal = "video"
            elif miss_item["audio"]:
                # 只缺失音频
                audio_tensor = models['processor']['audio'](audio_path)
                modal = "audio"
            else:
                # 都不缺失
                video_tensor = models['processor']['video'](video_path)
                audio_tensor = models['processor']['audio'](audio_path)[0]
                modal = "video_audio"

            # 输出预测
            prompt = get_prompt(text)
            output = mm_infer(video_tensor, prompt, model=models["model"], tokenizer=models["tokenizer"], modal=modal,
                              bert_tokeni=models["bert_tokenizer"], do_sample=False, audio=audio_tensor)

            predict_results.append(output)

    return predict_results


def noise_predict(models, data_path, raw_data_dir, noise_marks):
    predict_results = []

    with open(data_path, mode='r', encoding='utf-8') as file:
        data = csv.DictReader(file)

        for item, noise_item in zip(data, noise_marks):
            if item['mode'] != 'test':
                continue

            text = item['text']
            video_path = os.path.join(raw_data_dir+"/video", item['id']+".mp4")
            audio_path = os.path.join(raw_data_dir+"/audio", item['id']+".wav")

            modal = "video_audio"

            if noise_item["text"]:
                # 文本噪声，随机读取含有噪声的数据
                text_noise_file = TEXT_NOISE_FILES[random.randint(0, len(TEXT_NOISE_FILES) - 1)]
                text_noise_file_path = os.path.join(f"/home/dataset/{DATASET}/processed/text", text_noise_file)
                with open(text_noise_file_path, 'r', encoding='utf-8') as file:
                    text_datas = json.load(file)
                text = text_datas[item['id']]
            if noise_item["audio"]:
                # 音频噪声，随机读取含有噪声的数据
                audio_dir = f"/home/dataset/{DATASET}/processed/audio/" + AUDIO_NOISE_FILES[
                    random.randint(0, len(AUDIO_NOISE_FILES) - 1)]
                audio_path = os.path.join(audio_dir, item['id']+".wav")
            if noise_item["visual"]:
                # 视觉噪声，随机读取含有噪声的数据
                video_dir = f"/home/dataset/{DATASET}/processed/video/" + VIDEO_NOISE_FILES[
                    random.randint(0, len(VIDEO_NOISE_FILES) - 1)]
                video_path = os.path.join(video_dir, item['id']+".mp4")

            video_tensor = models['processor']['video'](video_path)
            audio_tensor = models['processor']['audio'](audio_path)[0]

            # 输出预测
            prompt = get_prompt(text)
            output = mm_infer(video_tensor, prompt, model=models["model"], tokenizer=models["tokenizer"], modal=modal,
                              bert_tokeni=models["bert_tokenizer"], do_sample=False, audio=audio_tensor)

            predict_results.append(output)

    return predict_results


def evaluate(pred_results, data_path):
    # 真实标签
    truths = []
    with open(data_path, mode='r', encoding='utf-8') as file:
        data = csv.DictReader(file)
        for item in data:
            if item['mode'] != 'test':
                continue
            truths.append(float(item['label'].strip()))

    # 预测标签
    preds = []
    for item in pred_results:
        match = re.search(r'[+-]?\d*\.?\d+', item)
        if match:
            preds.append(float(match.group(0)))
        else:
            raise ValueError("预测结果有误")

    # 七分类
    truths = np.array(truths)
    preds = np.array(preds)
    test_preds_a7 = np.clip(preds, a_min=-3., a_max=3.)
    test_truth_a7 = np.clip(truths, a_min=-3., a_max=3.)
    acc7 = np.sum(np.round(test_preds_a7) == np.round(truths)) / float(len(test_truth_a7))
    mae_7 = np.mean(np.absolute(preds - truths))
    corr_7 = np.corrcoef(preds, truths)[0][1]

    # 六分类（去掉 0）
    use_zero = False
    non_zeros = np.array([i for i, e in enumerate(truths) if e != 0 or use_zero])
    preds = preds[non_zeros]
    truths = truths[non_zeros]
    mae_6 = np.mean(np.absolute(preds - truths))
    corr_6 = np.corrcoef(preds, truths)[0][1]
    preds = preds >= 0
    truths = truths >= 0
    f_score = f1_score(truths, preds, average="weighted")
    acc2 = accuracy_score(truths, preds)

    results = {
        "acc7": acc7,
        "acc2": acc2,
        "f_score": f_score,
        "mae7": mae_7,
        "corr7": corr_7,
        "mae6": mae_6,
        "corr6": corr_6,
    }
    return results


def get_test_data_num(data_path):
    result = 0
    with open(data_path, mode='r', encoding='utf-8') as file:
        data = csv.DictReader(file)
        for item in data:
            if item['mode'] != 'test':
                continue
            result += 1

    return result


def save_pred_results(pred_results, evaluate_type=None, evaluate_detail=None):
    # 保存预测结果
    if evaluate_detail is None and evaluate_type is None:
        output_path = f"./result/{DATASET}.json"
    else:
        output_path = f"./result/{DATASET}_{evaluate_type}_{evaluate_detail}.json"
    with open(output_path, "w") as file:
        json.dump(pred_results, file)


def model_predict(models, data_path, raw_data_dir, evaluate_type=None):
    # 获取测试数据个数
    data_len = get_test_data_num(data_path)

    # 根据评估类型选择缺失/噪声测试
    if evaluate_type == "miss_rate":
        miss_rates = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
        for miss_rate in miss_rates:
            miss_marks = generate_miss_rate(miss_rate, data_len)
            print("Predicting...")
            pred_results = miss_predict(models, data_path, raw_data_dir, miss_marks)
            # 保存预测结果
            save_pred_results(pred_results, evaluate_type, miss_rate)
    elif evaluate_type == "miss_Probability":
        miss_probabilitys = [0.1, 0.3, 0.5, 0.7, 0.9]
        for miss_probability in miss_probabilitys:
            miss_marks = generate_miss_probability(miss_probability, data_len)
            print("Predicting...")
            pred_results = miss_predict(models, data_path, raw_data_dir, miss_marks)
            # 保存预测结果
            save_pred_results(pred_results, evaluate_type, miss_probability)
    elif evaluate_type == "noise_rate":
        noise_rates = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        for noise_rate in noise_rates:
            noise_marks = generate_noise_rate(noise_rate, data_len)
            print("Predicting...")
            pred_results = noise_predict(models, data_path, raw_data_dir, noise_marks)
            # 保存预测结果
            save_pred_results(pred_results, evaluate_type, noise_rate)
    elif evaluate_type == "noise_Probability":
        noise_probabilitys = [0.1, 0.3, 0.5, 0.7, 0.9]
        for noise_probability in noise_probabilitys:
            noise_marks = generate_noise_probability(noise_probability, data_len)
            print("Predicting...")
            pred_results = noise_predict(models, data_path, raw_data_dir, noise_marks)
            # 保存预测结果
            save_pred_results(pred_results, evaluate_type, noise_probabilitys)
    else:
        # 无缺失、无噪声，正常评估
        print("Predicting...")
        pred_results = predict(models, data_path, raw_data_dir)
        # 保存预测结果
        save_pred_results(pred_results)

    return pred_results


def main():
    model_path = f"/home/lms/codes/HumanOmni-main/scripts/checkpoints/{DATASET}/HumanOmni"
    lora_path = f"/home/lms/codes/HumanOmni-main/scripts/checkpoints/{DATASET}/HumanOmni-lora"
    data_path = f"/home/datasets/{DATASET}/label.csv"
    raw_data_dir = f"/home/datasets/{DATASET}"

    # 获取模型
    models = get_model(model_path, lora_path)

    # 预测
    pred_results = model_predict(models, data_path, raw_data_dir, args.evaluate_type)

    # 评估
    evaluate_results = evaluate(pred_results, data_path)

    # 保存 csv






if __name__ == '__main__':
    main()