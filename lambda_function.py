
import urllib.request
import json
import boto3
import os

s3 = boto3.resource('s3')
s3client = boto3.client('s3')
sns = boto3.client('sns', region_name='us-east-1')


## list_to_filterリストのうち、sequenceリストに含まれない要素にフィルタして返却する。
def not_in_filter(list_to_filter, sequence):
  return list(filter(lambda x: x not in sequence, list_to_filter))


## iprangesリストから、WorkSpacesで用いられるIPレンジを抽出する。
def get_ws_list(ip_ranges):
  ws_list = [
      {'region': 'GLOBAL', 'service': 'AMAZON'},
      {'region': 'ap-northeast-1', 'service': 'AMAZON'},
      {'region': 'us-east-1', 'service': 'AMAZON'},
      {'region': 'us-west-2', 'service': 'AMAZON'},
      {'region': 'us-west-2', 'service': 'S3'},
      {'region': 'ap-northeast-1', 'service': 'WORKSPACES_GATEWAYS'}
  ]

  ws_ipranges = {'iprange': [], 'iprange_foctet': []}

  for iprange in ip_ranges:
    for elem in ws_list:
      if iprange['region'] == elem['region'] and iprange['service'] == elem['service']:
        ws_ipranges['iprange'].append(iprange)
        ws_ipranges['iprange_foctet'].append(iprange['ip_prefix'].split('.')[0])
  
  return ws_ipranges


def lambda_handler(event, context):
  ## Webで現在公開されているAWSサービスのIPレンジのJSONを取得しiprangesに格納
  url = 'https://ip-ranges.amazonaws.com/ip-ranges.json'
  req = urllib.request.Request(url)
  with urllib.request.urlopen(req) as res:
    ipranges = json.load(res)

  ##ip-ranges.jsonをS3に保存（日付をつける）
  bucket_name = os.environ['BUCKET_NAME']
  json_key = 'ipranges-' + ipranges['createDate'] + '.json'
  obj = s3.Object(bucket_name,json_key)
  obj.put(Body = json.dumps(ipranges))

  ## 比較対象がない場合は処理を終了
  s3objlist = []
  s3obj=s3client.list_objects(Bucket=bucket_name)
  if len(s3obj['Contents']) == 1:
    return 'nothing previous ipranges'
  
  ## 一つ前のip-ranges.jsonを読み込む
  for i in s3obj['Contents']:
    s3objlist.append(i['Key'])

  s3objlist.sort(reverse=True)
  print(s3objlist)
  res = s3client.get_object(Bucket=bucket_name, Key=s3objlist[1])
  prev_ipranges = json.loads(res['Body'].read())

  ## テスト用コード
#  num_cur = int(os.environ['TEST_VERSION'])
#  res = s3client.get_object(Bucket=bucket_name, Key=s3objlist[num_cur])
#  ipranges = json.loads(res['Body'].read())
#  print(s3objlist[num_cur])
#  res = s3client.get_object(Bucket=bucket_name, Key=s3objlist[num_cur+1])
#  prev_ipranges = json.loads(res['Body'].read())
#  print(s3objlist[num_cur+1])
  
  ## IPリストの増減を比較
  added_ip_ranges = not_in_filter(ipranges['prefixes'], prev_ipranges['prefixes'])
  deleted_ip_ranges = not_in_filter(prev_ipranges['prefixes'],ipranges['prefixes'])

  ## ws_listに合致するリストを取得
  ws_ipranges = get_ws_list(ipranges['prefixes'])
  ws_ipranges_prev = get_ws_list(prev_ipranges['prefixes'])
  
  ## ws_listに合致するIPリストの増減を比較
  added_ws_ip_ranges = not_in_filter(ws_ipranges['iprange'], ws_ipranges_prev['iprange'])
  deleted_ws_ip_ranges = not_in_filter(ws_ipranges_prev['iprange'], ws_ipranges['iprange'])
  added_ws_ip_foctet_ranges = not_in_filter(ws_ipranges['iprange_foctet'], ws_ipranges_prev['iprange_foctet'])
  deleted_ws_ip_foctet_ranges = not_in_filter(ws_ipranges_prev['iprange_foctet'], ws_ipranges['iprange_foctet'])

  # log
  print('added ip ranges: ', added_ip_ranges)
  print('deleted ip ranges: ', deleted_ip_ranges)
  print('workspaces ip ranges: ', ws_ipranges['iprange'])
  print('workspaces ip first octet: ', ws_ipranges['iprange_foctet'])
  print('previous workspaces ip ranges: ', ws_ipranges_prev['iprange'])
  print('previous workspaces ip first octet: ', ws_ipranges_prev['iprange_foctet'])
  print('added ws ip ranges: ', added_ws_ip_ranges)
  print('deleted ws ip ranges: ', deleted_ws_ip_ranges)
  print('added ws first octet ip ranges: ', added_ws_ip_foctet_ranges)
  print('deleted ws first octet ip ranges: ', deleted_ws_ip_foctet_ranges)


  ## SNSメッセージ出力
  snsmsg = 'AWSのIPレンジに変更がありました。\n'

  if added_ws_ip_ranges or deleted_ws_ip_ranges:
    snsmsg += 'WorkSpacesの利用するIPレンジに変更がありました。\n'

    if added_ws_ip_foctet_ranges or deleted_ws_ip_foctet_ranges:
      snsmsg += 'WorkSpacesの利用するIPレンジの第一オクテットに変更があったため、設定変更が必要です。\n'
    else:
      snsmsg += 'WorkSpacesの利用するIPレンジの第一オクテットには変更はありませんでした。\n'

  else:
    snsmsg += 'WorkSpacesの利用するIPレンジに変更はありませんでした。\n'
  
  snsmsg += '\n\n'
  snsmsg += ipranges['createDate'] +'.json と '+ prev_ipranges['createDate'] +'.jsonの比較(IPv4)\n'
  snsmsg += '---WorkSpaces関連で増えた内容（' + ipranges['createDate'] + '.jsonにのみ記載）---\n'
  for ls in added_ws_ip_ranges:
    snsmsg += str(ls) + '\n'

  snsmsg += '\n\n'
  snsmsg += '---WorkSpaces関連で減った内容（' + prev_ipranges['createDate'] + '.jsonにのみ記載）---\n'
  for ls in deleted_ws_ip_ranges:
    snsmsg += str(ls) + '\n'

  snsmsg += '\n\n'
  snsmsg += '---全体で増えた内容（' + ipranges['createDate'] + '.jsonにのみ記載）---\n'
  for ls in added_ip_ranges:
    snsmsg += str(ls) + '\n'

  snsmsg += '\n\n'
  snsmsg += '---全体で減った内容（' + prev_ipranges['createDate'] + '.jsonにのみ記載）---\n'
  for ls in deleted_ip_ranges:
    snsmsg += str(ls) + '\n'

  sns_responce = sns.publish(
    TopicArn = os.environ['TOPIC_ARN'],
    Message = snsmsg,
    Subject = 'diff-ipranges'  
  )

  print(snsmsg)

  return 'Complete!'