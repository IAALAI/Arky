from fastapi import APIRouter
from fastapi import Request, HTTPException

from ..util.faketime import faketime
from ..const.filepath import RES_EXCEL_DIRPATH

from ..const.json_const import true, false, null
from ..const.filepath import CONFIG_JSON, VERSION_JSON
from ..util.const_json_loader import const_json_loader
from ..util.player_data import player_data_decorator

router = APIRouter()


@router.post("/building/sync")
@player_data_decorator
async def building_sync(player_data, request: Request):
    return _base_action(player_data, {}, "sync")


def _base_action(player_data, body, action):
    from ..protocol.building import dispatch
    aliases = {"change": "change_manufacture", "settle": "settle_manufacture"}
    try:
        return dispatch(player_data, aliases.get(action, action), body, faketime())
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/building/changeManufactureSolution")
@player_data_decorator
async def building_changeManufactureSolution(player_data, request: Request):
    return _base_action(player_data, await request.json(), "change")


@router.post("/building/settleManufacture")
@player_data_decorator
async def building_settleManufacture(player_data, request: Request):
    return _base_action(player_data, await request.json(), "settle")


@router.post("/building/getRecentVisitors")
async def building_getRecentVisitors(request: Request):
    request_json = await request.json()
    response = {"visitors": []}
    return response


@router.post("/building/getInfoShareVisitorsNum")
async def building_getInfoShareVisitorsNum(request: Request):
    request_json = await request.json()
    response = {"num": 0}
    return response


@router.post("/building/getClueFriendList")
@player_data_decorator
async def building_getClueFriendList(player_data, request: Request):
    request_json = await request.json()
    response = {"result": []}
    return response


@router.post("/building/getClueBox")
@player_data_decorator
async def building_getClueBox(player_data, request: Request):
    request_json = await request.json()
    response = {"box": []}
    return response


@router.post("/building/getAssistReport")
@player_data_decorator
async def building_getAssistReport(player_data, request: Request):
    request_json = await request.json()
    response = {"reports": []}
    return response


@router.post("/building/changeDiySolution")
@player_data_decorator
async def building_changeDiySolution(player_data, request: Request):
    request_json = await request.json()

    room_id = request_json["roomSlotId"]
    diy_solution = request_json["solution"]

    room_type = player_data["building"]["roomSlots"][room_id]["roomId"]

    player_data["building"]["rooms"][room_type][room_id]["diySolution"] = diy_solution

    response = {}
    return response


@router.post("/building/setBuildingAssist")
@player_data_decorator
async def building_setBuildingAssist(player_data, request: Request):
    return _base_action(player_data, await request.json(), "assist")


@router.post("/building/assignChar")
@player_data_decorator
async def building_assignChar(player_data, request: Request):
    return _base_action(player_data, await request.json(), "assign")


@router.post("/building/getMessageBoardContent")
@player_data_decorator
async def building_getMessageBoardContent(player_data, request: Request):
    request_json = await request.json()

    response = {
        "thisWeekVisitors": [],
        "lastWeekVisitors": [],
        "todayVisit": 0,
        "weeklyVisit": 0,
        "lastWeekVisit": 0,
        "lastWeekSpReward": 0,
        "lastShowTs": 1700000000,
    }
    return response


@router.post("/building/changeBGM")
@player_data_decorator
async def building_changeBGM(player_data, request: Request):
    request_json = await request.json()

    music_id = request_json["musicId"]

    player_data["building"]["music"]["selected"] = music_id

    response = {}
    return response


@router.post("/building/setPrivateDormOwner")
@player_data_decorator
async def building_setPrivateDormOwner(player_data, request: Request):
    request_json = await request.json()

    room_id = request_json["slotId"]
    char_num_id = request_json["charInsId"]

    player_data["building"]["rooms"]["PRIVATE"][room_id]["owners"] = [char_num_id]

    response = {}
    return response


@router.post("/building/saveDiyPresetSolution")
@player_data_decorator
async def building_saveDiyPresetSolution(player_data, request: Request):
    request_json = await request.json()

    solution_id = request_json["solutionId"]

    player_data["building"]["diyPresetSolutions"][str(solution_id)] = {
        "name": request_json["name"],
        "solution": request_json["solution"],
        "roomType": request_json["roomType"],
        "thumbnail": "http://127.0.0.1/thumbnail.jpg",
    }

    response = {}
    return response


@router.post("/building/getThumbnailUrl")
async def building_getThumbnailUrl(request: Request):
    request_json = await request.json()

    response = {"url": ["http://127.0.0.1/thumbnail.jpg"]}
    return response


@router.post("/building/changePresetName")
@player_data_decorator
async def building_changePresetName(player_data, request: Request):
    request_json = await request.json()

    solution_id = request_json["solutionId"]

    player_data["building"]["diyPresetSolutions"][str(solution_id)]["name"] = (
        request_json["name"]
    )

    response = {}
    return response


def _command_endpoint(action):
    @player_data_decorator
    async def endpoint(player_data, request: Request):
        return _base_action(player_data, await request.json(), action)
    return endpoint

for _path, _action in {
    "changeStrategy": "strategy", "deliveryOrder": "deliver",
    "deliveryBatchOrder": "deliver_batch", "deleteOrder": "delete_order",
    "accelerateOrder": "accelerate_order", "accelerateSolution": "accelerate_manufacture",
    "workshopSynthesis": "workshop", "upgradeSpecialization": "start_training",
    "completeUpgradeSpecialization": "finish_training",
}.items():
    router.add_api_route("/building/" + _path, _command_endpoint(_action), methods=["POST"], name="building_" + _path)
