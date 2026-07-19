import argparse
import csv
import os
import json


def get_conversation(dataset, text):
    if dataset == 'sims' or dataset == 'simsv2':
        prompt = (f"<video>\n<audio>\nSentiment scores range from -1 to +1, where -1 is highly negative, "
                  f"+1 is highly positive, and 0 is neutral.The speaker said '{text}'."
                  f"What is the sentiment score of the person in the video based on visual,audio and text? "
                  f"Directly answer the sentiment score.")
    elif dataset == 'mosi' or dataset == 'mosei':
        prompt = (f"<video>\n<audio>\nSentiment scores range from -3 to +3, where -3 is highly negative, "
                  f"+3 is highly positive, and 0 is neutral.The speaker said '{text}'."
                  f"What is the sentiment score of the person in the video based on visual,audio and text? "
                  f"Directly answer the sentiment score.")
    elif dataset == 'meld':
        prompt = (f"<video>\n<audio>\nThe speaker said: {text}. Based on the textual, visual, and audio content, "
                  f"what is the emotion of this speaker?")
    elif dataset == 'urfunny2':
        prompt = (f"<video>\n<audio>\nThe speaker said: {text}. Determine whether the content is humorous based on the visuals, "
                  f"audio, and spoken words in the video. Respond with 'serious' or 'humorous'.")

    return prompt


def construct_data(data, id, video_dir, dataset):
    text = data['text']
    label = data['label']
    # 构造JSON
    result = {}
    # id, video, audio
    result['id'] = id
    result['video'] = os.path.join(video_dir, data['id']+'.mp4')
    # conversations
    conversations = []
    human_conversation = {}
    human_conversation['from'] = "human"
    human_conversation['value'] = get_conversation(dataset, text)
    gpt_conversation = {}
    gpt_conversation['from'] = "gpt"
    gpt_conversation['value'] = str(label)
    conversations.append(human_conversation)
    conversations.append(gpt_conversation)

    result['conversations'] = conversations

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='mosei',
                        choices=['mosi', 'mosei', 'meld', 'sims', 'simsv2', 'urfunny2'])
    args = parser.parse_args()

    data_path = f"/home/datasets/{args.dataset}/label.csv"
    video_dir = f"/home/datasets/{args.dataset}/raw/video"
    output_path = f"./finetune/json/{args.dataset}.json"

    id = 0  # 序号
    fune_tune_datas = []
    with open(data_path, mode="r", encoding="utf-8") as f:
        data = csv.DictReader(f)
        for item in data:
            if item["mode"] != "train":
                continue
            data_item = construct_data(item, id, video_dir, args.dataset)
            fune_tune_datas.append(data_item)
            id += 1

    # 保存文件
    with open(output_path, 'w') as f:
        json.dump(fune_tune_datas, f)

    print("END")


if __name__ == "__main__":
    main()
