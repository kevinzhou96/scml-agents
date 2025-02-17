from random import shuffle

import torch
from agent import *
from draw import plot
from hyperparameters import *
from patches import *
from scml import SCML2020World
from tqdm import tqdm
from utility_model import (
    UtilityModel,
    load_buyer_utility_model,
    load_seller_utiltiy_model,
)


def get_train_data(world):
    seller_train_data = []
    buyer_train_data = []
    for agent in world.agents.values():
        if not "MyL" in agent.name:
            continue

        seller_data = [
            negotiation
            for negotiation in agent.neg_history[True].values()
            if len(negotiation) > 0
        ]
        seller_train_data.extend(seller_data)

        buyer_data = [
            negotiation
            for negotiation in agent.neg_history[False].values()
            if len(negotiation) > 0
        ]
        buyer_train_data.extend(buyer_data)

    return seller_train_data, buyer_train_data


def split_features_tags(data):
    features = []
    tags = []

    for sample_negotiation in data:
        neg_features = []
        neg_tags = []
        for message in sample_negotiation:
            neg_features.append(np.array(message[:RESPONSE_RELATIVE_TIME]))
            neg_tags.append(np.array(message[RESPONSE_RELATIVE_TIME:]))
        features.append(np.array(neg_features))
        tags.append(np.array(neg_tags))

    return features, tags


print("training...")
seller_train_data = []
buyer_train_data = []
for i in tqdm(range(UTILITY_TRAIN_DATA)):
    world = SCML2020World(
        **SCML2020World.generate(
            agent_types=[
                MyLearnUtilityAgent,
                DecentralizingAgent,
            ],
            n_steps=40,
            n_processes=2,
        ),
        construct_graphs=True
    )
    SCML2020World.cancelled_contracts = cancelled_contracts
    world.run()
    plot(world)

    seller_data, buyer_data = get_train_data(world)
    seller_train_data += seller_data
    buyer_train_data += buyer_data

seller_train_features, seller_train_tags = split_features_tags(seller_train_data)
seller_train_features = [
    torch.from_numpy(feature).float() for feature in seller_train_features
]
seller_train_tags = [torch.from_numpy(tag).float() for tag in seller_train_tags]

all_seller_data = list(zip(seller_train_features, seller_train_tags))
shuffle(all_seller_data)
train_seller_data = all_seller_data[
    : -int(len(all_seller_data) * UTILITY_VALIDATION_SPLIT)
]
test_seller_data = all_seller_data[
    -int(len(all_seller_data) * UTILITY_VALIDATION_SPLIT) :
]

buyer_train_features, buyer_train_tags = split_features_tags(buyer_train_data)
buyer_train_features = [
    torch.from_numpy(feature).float() for feature in buyer_train_features
]
buyer_train_tags = [torch.from_numpy(tag).float() for tag in buyer_train_tags]

all_buyer_data = list(zip(buyer_train_features, buyer_train_tags))
shuffle(all_buyer_data)
train_buyer_data = all_buyer_data[
    : -int(len(all_buyer_data) * UTILITY_VALIDATION_SPLIT)
]
test_buyer_data = all_buyer_data[-int(len(all_buyer_data) * UTILITY_VALIDATION_SPLIT) :]

if UTILITY_LOAD_MODEL:
    seller_model = load_seller_utiltiy_model(path=UTILITY_SELL_PATH)
    buyer_model = load_buyer_utility_model(path=UTILITY_BUY_PATH)
else:
    seller_model = UtilityModel(True)
    buyer_model = UtilityModel(False)

if UTILITY_TRAIN_SELLER:
    print("seller training...")
    train_seller, valid_seller = seller_model.fit(
        train_seller_data,
        test_seller_data,
        save_model=UTILITY_SAVE_MODEL,
        path=UTILITY_SELL_PATH,
    )
    seller_model.plot(train_seller, valid_seller)


if UTILITY_TRAIN_BUYER:
    print("buyer training...")
    train_buyer, valid_buyer = buyer_model.fit(
        train_buyer_data,
        test_buyer_data,
        save_model=UTILITY_SAVE_MODEL,
        path=UTILITY_BUY_PATH,
    )
    buyer_model.plot(train_buyer, valid_buyer)

print("done")
