-- ==========================================
-- AUTO CHEST LOOTER (SERVER HOP & WEBHOOK)
-- ==========================================
local Players = game:GetService("Players")
local LocalPlayer = Players.LocalPlayer
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TeleportService = game:GetService("TeleportService")
local HttpService = game:GetService("HttpService")
local workspace = game:GetService("Workspace")

local PlaceId = game.PlaceId

-- ==========================================
-- RESTRICTED PLACE ID CHECK
-- ==========================================
local restrictedPlaces = {113625171130061, 18859833719}
if table.find(restrictedPlaces, PlaceId) then
    print("Restricted Place ID detected (" .. PlaceId .. "). Script will not run to avoid interfering.")
    return 
end

-- ==========================================
-- ITEM BLACKLIST
-- ==========================================
-- Type the names of the items you DO NOT want to loot. (Leave blank to take everything)
-- Example: {"Goblin Ear", "Bone", "Broken Sword"}
local BlacklistedItems = {
    
}

local function IsBlacklisted(itemName)
    local lowerName = string.lower(itemName)
    for _, v in ipairs(BlacklistedItems) do
        if string.lower(v) == lowerName then
            return true
        end
    end
    return false
end

-- ==========================================
-- CUSTOM CLASSIFICATION LISTS
-- ==========================================
-- Add exactly as spelled, or close to it. The script ignores apostrophes and casing.
local CustomArmor = {
    "Overlord's Helmet", "Overlord's Chestplate", "Overlord's Legpiece",
    "Redguard Helmet", "Redguard Breastplate", "Redguard Legpiece",
    "Harbinger's Mask", "Harbinger's Chestplate", "Harbinger's Legpiece",
    "Crusader Helm", "Crusader Chestguard", "Crusader Legpiece",
    "Stalwart Helm", "Stalwart Chestguard", "Stalwart Legplates",
    "Sinweave's Hood", "Sinweave's Robe", "Sinweave's Legpiece",
    "Hollow Vanguard's Helm", "Hollow Vanguard's Cuirass", "Hollow Vanguard's Greaves",
    "Feudal Hat", "Feudal Robe", "Feudal Pants",
    "Pale Sentinel Visor", "Pale Sentinel Cuirass", "Pale Sentinel Greaves",
    "Pale Warden Helmet", "Pale Warden Cuirass", "Pale Warden Greaves", "Archangel's Halo",
	"Archangel's Chestplate", "Archangel's Greaves"
}

local CustomNeckwear = {
    "Fleetstep Chain", "Giant's Measure", "Grim Ward", "Spellward Amulet",
    "Clarity Loop", "Bloodstone Pendant", "Coincaller Pendant", "Coincaller's Coin",
    "Bear Charm", "Featherfall Torque", "Stillwind Locket", "Purity Rosary",
    "Yakubian Tricknology", "Fleetchain", "Master Amulet", "Executioner's Eye",
    "Runed Torque", "Verdant Coil", "Glassheart Reliquary", "The Lesser Crown",
    "Slayer's Sigil", "Seer Necklace", "Rite of Absolution", "Crimson Amulet", 
	"Frostfire Amulet", "Hidden Amulet", "Lannis Amulet", "Philosopher's Pendant", 
	"Rite of Communion", "Wisp Locket", "Wispbound Halo", "Blinkstep Medallion", 
	"Balanced Medallion", "Focus Medallion", "Quickstep Locket", "Hunter's Chain", 
	"Dying Flame Amulet", "Vital Loop", "Ironbound Pendant", "Lucent Sigil", 
	"Rite of Sacrifice"
}

-- Normalizer removes spaces, apostrophes, and makes it lowercase for foolproof matching
local function NormalizeStr(str)
    return string.lower(string.gsub(str, "[%p%s]", ""))
end

local ArmorLookup = {}
for _, v in pairs(CustomArmor) do ArmorLookup[NormalizeStr(v)] = true end

local NeckwearLookup = {}
for _, v in pairs(CustomNeckwear) do NeckwearLookup[NormalizeStr(v)] = true end

-- ==========================================
-- WEBHOOK SETUP
-- ==========================================
-- Paste your Discord Webhook URL here:
local WEBHOOK_URL = "YOUR_WEBHOOK_URL_HERE"

local httprequest = (syn and syn.request) or (http and http.request) or http_request or request or HttpService.RequestAsync

local function CategorizeItem(itemName)
    local norm = NormalizeStr(itemName)
    local lowerName = string.lower(itemName)

    if ArmorLookup[norm] then return "Armor" end
    if NeckwearLookup[norm] then return "Neckwear" end

    for armorName, _ in pairs(ArmorLookup) do
        if string.find(norm, armorName) then return "Armor" end
    end
    for neckName, _ in pairs(NeckwearLookup) do
        if string.find(norm, neckName) then return "Neckwear" end
    end

    if lowerName:find("sword") or lowerName:find("scythe") or lowerName:find("pickaxe") or lowerName:find("warhammer") or lowerName:find("spear") or lowerName:find("axe") or lowerName:find("blade") then
        return "Weapons"
    elseif lowerName:find("ring") or lowerName:find("necklace") or lowerName:find("amulet") or lowerName:find("chestplate") or lowerName:find("armor") or lowerName:find("helmet") or lowerName:find("animus") then
        return "Equipment & Accessories"
    else
        return "Items & Consumables"
    end
end

local function SendWebhook(lootedItemsArray)
    if not httprequest or WEBHOOK_URL == "" or WEBHOOK_URL:find("YOUR_WEBHOOK") then return end

    local categorized = {
        ["Armor"] = {},
        ["Neckwear"] = {},
        ["Weapons"] = {},
        ["Equipment & Accessories"] = {},
        ["Items & Consumables"] = {}
    }

    local categoryEmojis = {
        ["Armor"] = "🛡️",
        ["Neckwear"] = "📿",
        ["Weapons"] = "🗡️",
        ["Equipment & Accessories"] = "💍",
        ["Items & Consumables"] = "📦"
    }

    for _, itemData in ipairs(lootedItemsArray) do
        local cat = CategorizeItem(itemData.Name)
        local itemText = "• [" .. itemData.Amount .. "x] : " .. itemData.Name
        
        if #itemData.Curses > 0 then
            itemText = itemText .. "\n   ↳ 🔮 *Curses: " .. table.concat(itemData.Curses, ", ") .. "*"
        end
        
        table.insert(categorized[cat], itemText)
    end

    local fields = {}
    for category, items in pairs(categorized) do
        if #items > 0 then
            table.insert(fields, {
                ["name"] = categoryEmojis[category] .. " ---- " .. category .. " ----",
                ["value"] = table.concat(items, "\n"),
                ["inline"] = false
            })
        end
    end

    local data = {
        ["embeds"] = {{
            ["title"] = "Chest Looted Successfully!",
            ["color"] = tonumber(0x00FF00), 
            ["fields"] = fields,
            ["footer"] = {
                ["text"] = "Player: " .. LocalPlayer.Name .. " | Auto Looter"
            },
            ["timestamp"] = DateTime.now():ToIsoDate()
        }}
    }

    pcall(function()
        httprequest({
            Url = WEBHOOK_URL,
            Method = "POST",
            Headers = {["Content-Type"] = "application/json"},
            Body = HttpService:JSONEncode(data)
        })
    end)
end

-- ==========================================
-- SERVER HOP LOGIC
-- ==========================================
local function ServerHop()
    print("Initiating Server Hop...")
    local serversApi = "https://games.roblox.com/v1/games/" .. PlaceId .. "/servers/Public?sortOrder=Desc&limit=100"
    
    local success, result = pcall(function()
        return game:HttpGet(serversApi)
    end)
    
    if success and result then
        local data = HttpService:JSONDecode(result)
        if data and data.data then
            for _, server in ipairs(data.data) do
                if server.playing < server.maxPlayers and server.id ~= game.JobId then
                    print("Found new server! Teleporting...")
                    TeleportService:TeleportToPlaceInstance(PlaceId, server.id, LocalPlayer)
                    task.wait(10)
                end
            end
        end
    end
    
    TeleportService:Teleport(PlaceId, LocalPlayer)
end

-- ==========================================
-- FAILSAFES: HP MONITOR & 5-MIN IDLE HOPPER
-- ==========================================
getgenv().LastChestLootTime = tick() -- Global tracker for the 5-minute failsafe

task.spawn(function()
    local timeDead = 0
    while task.wait(1) do
        -- 1. Death Monitor
        local char = LocalPlayer.Character
        local hum = char and char:FindFirstChild("Humanoid")
        
        if not char or (hum and hum.Health <= 0) then
            timeDead = timeDead + 1
            print("Character Dead! Firing Regenerate Remote... (" .. timeDead .. "s)")
            
            pcall(function()
                local Event = ReplicatedStorage.StoragePackage.Communication.Client.Regenerate
                Event:FireServer(1)
            end)
            
            if timeDead >= 20 then
                print("Failed to respawn after 20 seconds. Server hopping...")
                ServerHop()
                break
            end
        else
            timeDead = 0
        end

        -- 2. 5-Minute Idle Monitor
        if (tick() - getgenv().LastChestLootTime) >= 300 then
            print("FAILSAFE: No chests successfully opened in 5 minutes! Server Hopping...")
            ServerHop()
            break
        end
    end
end)

-- ==========================================
-- REMOTE EVENT SETUP & WIRETAPS
-- ==========================================
local Comm = ReplicatedStorage:WaitForChild("StoragePackage"):WaitForChild("Communication")
local ContainerUpdate = Comm:WaitForChild("Remote"):WaitForChild("Inventory"):WaitForChild("ContainerUpdate")
local ItemAction = Comm:WaitForChild("Remote"):WaitForChild("Inventory"):WaitForChild("ItemAction")
local Notification = Comm:WaitForChild("Client"):WaitForChild("Notification")

local currentChestData = nil
local notificationsReceived = 0
local lastNotifTime = tick()

ContainerUpdate.OnClientEvent:Connect(function(itemsTable, containerId, centerPart, containerType)
    if type(itemsTable) == "table" and type(containerId) == "number" then
        currentChestData = {
            Items = itemsTable,
            Id = containerId
        }
    end
end)

Notification.OnClientEvent:Connect(function(notifType, amount, itemName, color)
    if notifType == "Item" then
        notificationsReceived = notificationsReceived + 1
        lastNotifTime = tick()
    end
end)

-- ==========================================
-- SAFE INCREMENTAL TP
-- ==========================================
local function IncrementalTP(targetPos)
    local char = LocalPlayer.Character
    local root = char and char:FindFirstChild("HumanoidRootPart")
    if not root then return end
    
    local hum = char:FindFirstChildWhichIsA("Humanoid")
    if hum then
        hum.PlatformStand = false
        if hum:GetState() == Enum.HumanoidStateType.Physics or hum:GetState() == Enum.HumanoidStateType.Ragdoll then
            hum:ChangeState(Enum.HumanoidStateType.GettingUp)
        end
    end
    
    local step = 10
    while root and root.Parent do
        local dist = (targetPos - root.Position).Magnitude
        if dist <= step then
            root.Velocity = Vector3.zero
            root.CFrame = CFrame.new(targetPos)
            task.wait(0.1)
            break
        else
            local dir = (targetPos - root.Position).Unit
            root.Velocity = Vector3.zero
            root.CFrame = root.CFrame + (dir * step)
            task.wait(0.05) 
        end
    end
end

-- ==========================================
-- ADVANCED CHEST LOCATOR (With States)
-- ==========================================
local chestStates = {} 
local hasDeferredFirstChest = false

local function GetUnlootedChests()
    local tempChests = {}
    local world = workspace:FindFirstChild("World")
    if not world then return tempChests end

    for _, prompt in ipairs(world:GetDescendants()) do
        if prompt:IsA("ProximityPrompt") and prompt.Name == "Interact" then
            local center = prompt.Parent
            if center and center.Name == "Center" then
                local chestModel = center.Parent
                if chestModel and chestStates[chestModel] ~= "Done" then
                    local char = LocalPlayer.Character
                    local root = char and char:FindFirstChild("HumanoidRootPart")
                    local dist = root and (root.Position - center.Position).Magnitude or math.huge
                    
                    table.insert(tempChests, {
                        Model = chestModel,
                        Root = center,
                        Prompt = prompt,
                        Distance = dist,
                        State = chestStates[chestModel] or "Fresh"
                    })
                end
            end
        end
    end
    
    table.sort(tempChests, function(a, b) return a.Distance < b.Distance end)

    if not hasDeferredFirstChest and #tempChests > 0 then
        hasDeferredFirstChest = true
        chestStates[tempChests[1].Model] = "Deferred"
        tempChests[1].State = "Deferred"
    end

    local priorityMap = { ["Fresh"] = 1, ["FailedOnce"] = 2, ["Deferred"] = 3 }
    table.sort(tempChests, function(a, b)
        local pA = priorityMap[a.State]
        local pB = priorityMap[b.State]
        if pA == pB then
            return a.Distance < b.Distance
        end
        return pA < pB
    end)

    return tempChests
end

-- ==========================================
-- MAIN FARM LOOP
-- ==========================================
local function AutoFarmChests()
    print("Starting Server-Intercept Chest Looter with Webhooks & Smart Retries...")
    
    local isFirstChestSkipPending = true 
    
    while task.wait(1) do
        local chests = GetUnlootedChests()
        
        if #chests == 0 then
            print("No chests found! Waiting 5 seconds to double check before hopping...")
            task.wait(5)
            chests = GetUnlootedChests()
            if #chests == 0 then
                print("Confirmed 0 chests remaining.")
                ServerHop()
                break 
            end
        end
        
        local target = chests[1]
        
        if isFirstChestSkipPending then
            if #chests > 1 and chests[2].State == "Fresh" then
                target = chests[2]
                print("Skipping the closest chest for now. Targeting the 2nd nearest instead.")
            end
            isFirstChestSkipPending = false 
        end
        
        local success = false
        local currentChestLoot = {} 
        
        for attempt = 1, 2 do
            if attempt == 1 then
                print("\nMoving to Chest [" .. target.State .. "]:", target.Model.Name, "| Distance:", math.floor(target.Distance))
            else
                print("\n[RETRY] Ragdoll/Bug detected. Re-teleporting to Chest...")
            end
            
            IncrementalTP(target.Root.Position)
            task.wait(0.5)
            
            currentChestData = nil
            currentChestLoot = {}
            notificationsReceived = 0
            lastNotifTime = tick()
            
            for i = 1, 6 do 
                if target.Prompt and fireproximityprompt then
                    fireproximityprompt(target.Prompt)
                end
                task.wait(0.5)
                if currentChestData then break end
            end
            
            if currentChestData then
                print("Chest opened! Extracting items...")
                local items = currentChestData.Items
                local chestId = currentChestData.Id
                local itemsRequested = 0
                
                for _, item in ipairs(items) do
                    local uuid = item.Id
                    local name = item.Name
                    local amount = item.Amount or 1
                    local curses = {}

                    -- BLACKLIST CHECK
                    if IsBlacklisted(name) then
                        print("Skipping blacklisted item: " .. name)
                        continue 
                    end

                    if item.Attr and item.Attr.Curses then
                        for curseName, hasCurse in pairs(item.Attr.Curses) do
                            if hasCurse then
                                table.insert(curses, curseName)
                            end
                        end
                    end
                    
                    if uuid and name then
                        itemsRequested = itemsRequested + 1
                        
                        table.insert(currentChestLoot, {
                            Name = name, 
                            Amount = amount, 
                            Curses = curses
                        })
                        
                        pcall(function()
                            ItemAction:FireServer("TransferInventory", name, amount, chestId, true, uuid, nil)
                        end)
                        task.wait(0.05) 
                    end
                end
                
                if itemsRequested > 0 then
                    lastNotifTime = tick() 
                    
                    while notificationsReceived < itemsRequested and (tick() - lastNotifTime) < 1.5 do
                        task.wait(0.1)
                    end
                    
                    if notificationsReceived > 0 then
                        print("Looting finished for this chest!")
                        success = true
                        getgenv().LastChestLootTime = tick() -- Reset 5-minute failsafe timer
                        
                        local finalLoot = currentChestLoot
                        task.spawn(function()
                            SendWebhook(finalLoot)
                        end)
                    else
                        print("Requested items but received ZERO notifications. Ragdolled?")
                    end
                else
                    print("Chest was empty (or only contained blacklisted items)!")
                    success = true 
                    getgenv().LastChestLootTime = tick() -- Reset 5-minute failsafe timer
                end
                
                pcall(function()
                    Comm.Remote.Inventory.ContainerUpdate:FireServer()
                    Comm.Remote.Trinket_Nearby:InvokeServer()
                end)
                
            else
                print("Failed to get chest data from server. Prompt didn't register?")
            end
            
            if success then
                break
            else
                task.wait(2)
            end
        end
        
        if success then
            chestStates[target.Model] = "Done"
        else
            if target.State == "Fresh" then
                print("Chest failed completely. Marking as 'FailedOnce' to revisit later.")
                chestStates[target.Model] = "FailedOnce"
            elseif target.State == "FailedOnce" then
                print("Chest failed again on revisit. Skipping permanently.")
                chestStates[target.Model] = "Done"
            end
        end
        
        task.wait(0.5)
    end
end

-- Execute
task.spawn(AutoFarmChests)
