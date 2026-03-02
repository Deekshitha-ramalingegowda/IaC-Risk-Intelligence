resource "aws_vpc" "my_vpc" {

    cidr_block = ""
    tags = {
        Name = "my_vpc"
    }
  
}

resource "aws_subnet" "public_subnet" {
  vpc_id = aws_vpc.my_vpc.id
    cidr_block = ""
    availability_zone = "us-east-1a"
    tags = {
        Name = "public_subnet"
    }      
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.my_vpc.id
}

resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.my_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}

resource "aws_route_table_association" "rta" {
  subnet_id      = aws_subnet.public_subnet.id
  route_table_id = aws_route_table.public_rt.id
}
